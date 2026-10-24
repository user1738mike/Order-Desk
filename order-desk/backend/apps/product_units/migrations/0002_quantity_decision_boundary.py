"""Explicit unit decisions; invoker-only source verification and frozen copies."""

from django.db import migrations

INSTALL = r"""
CREATE FUNCTION public.orderdesk_unit_reference(p_line uuid,p_policy uuid,p_alias uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path=pg_catalog,public AS $$
 SELECT jsonb_build_object(
  'line_id',l.id,'draft_id',l.order_id,
  'requested',jsonb_build_object('sku',l.requested_sku,'description',l.requested_description,'quantity',l.quantity::text,'unit',l.unit),
  'product',jsonb_build_object('id',c.id,'sku',c.sku,'description',c.description,'updated_at',c.updated_at),
  'policy',jsonb_build_object('id',p.id,'updated_at',p.updated_at,'requested_token',p.requested_token,'provenance',p.provenance,
   'selling_numerator',p.selling_numerator::text,'selling_denominator',p.selling_denominator::text,'selling_scale',p.selling_scale,'selling_max_integer_digits',p.selling_max_integer_digits,
   'destination_numerator',p.destination_numerator::text,'destination_denominator',p.destination_denominator::text,'destination_scale',p.destination_scale,'destination_max_integer_digits',p.destination_max_integer_digits),
  'units',jsonb_build_object(
   'requested',jsonb_build_object('id',ru.id,'code',ru.code,'display_name',ru.display_name,'updated_at',ru.updated_at),
   'selling',jsonb_build_object('id',su.id,'code',su.code,'display_name',su.display_name,'updated_at',su.updated_at),
   'destination',CASE WHEN du.id IS NULL THEN 'null'::jsonb ELSE jsonb_build_object('id',du.id,'code',du.code,'display_name',du.display_name,'updated_at',du.updated_at) END),
  'alias',CASE WHEN a.id IS NULL THEN 'null'::jsonb ELSE jsonb_build_object('id',a.id,'value',a.value,'provenance',a.provenance,'updated_at',a.updated_at,'customer_id',a.customer_id) END,
  'customer',CASE WHEN cd.id IS NULL THEN 'null'::jsonb ELSE jsonb_build_object('id',cd.customer_id,'decision_id',cd.id) END)
 FROM public.orders_draftorderline l
 JOIN public.orders_draftorder d ON d.id=l.order_id AND d.organization_id=l.organization_id AND d.status='draft'
 JOIN public.catalog_catalogitem c ON c.id=l.catalogue_item_id AND c.organization_id=l.organization_id AND c.is_active
 JOIN public.product_units_productunitpolicy p ON p.id=p_policy AND p.organization_id=l.organization_id AND p.catalogue_item_id=c.id AND p.is_active AND p.requested_token=l.unit
 JOIN public.product_units_controlledunit ru ON ru.id=p.requested_unit_id AND ru.organization_id=l.organization_id AND ru.is_active
 JOIN public.product_units_controlledunit su ON su.id=p.selling_unit_id AND su.organization_id=l.organization_id AND su.is_active
 LEFT JOIN public.product_units_controlledunit du ON du.id=p.destination_unit_id AND du.organization_id=l.organization_id AND du.is_active
 LEFT JOIN public.customers_draftcustomerdecision cd ON cd.draft_id=d.id AND cd.organization_id=l.organization_id AND cd.is_current
 LEFT JOIN public.customers_customeraccount ca ON ca.id=cd.customer_id AND ca.organization_id=l.organization_id
 LEFT JOIN public.product_units_customerproductalias a ON a.id=p_alias AND a.organization_id=l.organization_id AND a.customer_id=cd.customer_id AND a.catalogue_item_id=c.id AND a.is_active AND a.value=l.requested_sku
 WHERE l.id=p_line AND l.quantity>0
 AND l.catalogue_sku_snapshot=c.sku AND l.catalogue_description_snapshot=c.description
 AND length(c.description)<=4096 AND length(l.requested_description)<=4096
 AND (p.destination_unit_id IS NULL OR du.id IS NOT NULL)
 AND (cd.id IS NULL OR (ca.is_active AND (cd.snapshot->'account'->>'updated_at')::timestamptz=ca.updated_at))
 AND (p_alias IS NULL OR (a.id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.catalog_catalogitem other WHERE other.organization_id=l.organization_id AND other.sku=a.value AND other.id<>c.id)));
$$;
REVOKE ALL ON FUNCTION public.orderdesk_unit_reference(uuid,uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.orderdesk_unit_reference(uuid,uuid,uuid) TO orderdesk_app,orderdesk_migrator;
CREATE FUNCTION public.orderdesk_unit_amount_valid(v jsonb,q numeric,n numeric,d numeric,s integer,m integer,u jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
BEGIN
 IF v IS NULL OR jsonb_typeof(v)<>'object' OR jsonb_typeof(v->'quantity')<>'string'
 OR v->'unit' IS DISTINCT FROM u OR (v->>'quantity') !~ ('^[0-9]{1,'||m||'}'||CASE WHEN s=0 THEN '' ELSE '\.[0-9]{'||s||'}' END||'$') THEN RETURN false; END IF;
 RETURN (v->>'quantity')::numeric>0 AND (v->>'quantity')::numeric*d=q*n;
END $$;
REVOKE ALL ON FUNCTION public.orderdesk_unit_amount_valid(jsonb,numeric,numeric,numeric,integer,integer,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.orderdesk_unit_amount_valid(jsonb,numeric,numeric,numeric,integer,integer,jsonb) TO orderdesk_app,orderdesk_migrator;
CREATE FUNCTION public.orderdesk_unit_decision_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE r jsonb; p record; q numeric;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF to_jsonb(NEW)-ARRAY['is_current','retired_at','retired_by_id','retirement_reason'] IS DISTINCT FROM to_jsonb(OLD)-ARRAY['is_current','retired_at','retired_by_id','retirement_reason']
   OR NOT OLD.is_current OR NEW.is_current OR (current_user='orderdesk_app' AND NEW.retired_by_id IS DISTINCT FROM NULLIF(current_setting('orderdesk.user_id',true),'')::uuid)
   OR NOT EXISTS(SELECT 1 FROM public.orders_draftorder WHERE id=NEW.draft_id AND organization_id=NEW.organization_id AND status='draft') THEN
    RAISE EXCEPTION 'Unit decision history is immutable' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 r=public.orderdesk_unit_reference(NEW.line_id,NEW.policy_id,NEW.alias_id);
 SELECT * INTO p FROM public.product_units_productunitpolicy WHERE id=NEW.policy_id AND organization_id=NEW.organization_id;
 q=(r->'requested'->>'quantity')::numeric;
 IF r IS NULL OR NOT NEW.is_current OR NEW.snapshot->'reference' IS DISTINCT FROM r
  OR NEW.draft_id::text IS DISTINCT FROM r->>'draft_id'
  OR NEW.catalogue_item_id::text IS DISTINCT FROM r->'product'->>'id'
  OR NEW.customer_id::text IS DISTINCT FROM r->'customer'->>'id'
  OR NEW.customer_decision_id::text IS DISTINCT FROM r->'customer'->>'decision_id'
  OR (current_user='orderdesk_app' AND NEW.actor_id IS DISTINCT FROM NULLIF(current_setting('orderdesk.user_id',true),'')::uuid)
  OR public.orderdesk_unit_amount_valid(NEW.snapshot->'selling',q,p.selling_numerator,p.selling_denominator,p.selling_scale,p.selling_max_integer_digits,r->'units'->'selling') IS DISTINCT FROM true
  OR (p.destination_unit_id IS NULL AND NEW.snapshot->'destination' IS DISTINCT FROM 'null'::jsonb)
  OR (p.destination_unit_id IS NOT NULL AND public.orderdesk_unit_amount_valid(NEW.snapshot->'destination',q,p.destination_numerator,p.destination_denominator,p.destination_scale,p.destination_max_integer_digits,r->'units'->'destination') IS DISTINCT FROM true) THEN
   RAISE EXCEPTION 'Unit decision source or exact quantity is invalid' USING ERRCODE='23514'; END IF;
 NEW.created_at=clock_timestamp();
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.orderdesk_unit_decision_guard() FROM PUBLIC;
CREATE TRIGGER unit_decision_guard BEFORE INSERT OR UPDATE ON public.product_units_draftlineunitdecision FOR EACH ROW EXECUTE FUNCTION public.orderdesk_unit_decision_guard();
CREATE FUNCTION public.orderdesk_unit_source_changed() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF TG_TABLE_NAME='orders_draftorderline' THEN
  IF (NEW.requested_sku,NEW.requested_description,NEW.quantity,NEW.unit,NEW.catalogue_item_id,NEW.catalogue_sku_snapshot,NEW.catalogue_description_snapshot) IS NOT DISTINCT FROM
     (OLD.requested_sku,OLD.requested_description,OLD.quantity,OLD.unit,OLD.catalogue_item_id,OLD.catalogue_sku_snapshot,OLD.catalogue_description_snapshot) THEN RETURN NEW; END IF;
  UPDATE public.product_units_draftlineunitdecision SET is_current=false,retired_at=clock_timestamp(),retired_by_id=NULLIF(current_setting('orderdesk.user_id',true),'')::uuid,retirement_reason='requested_line_changed' WHERE line_id=NEW.id AND organization_id=NEW.organization_id AND is_current;
 ELSE
  IF OLD.is_current AND NOT NEW.is_current THEN
   UPDATE public.product_units_draftlineunitdecision SET is_current=false,retired_at=clock_timestamp(),retired_by_id=NULLIF(current_setting('orderdesk.user_id',true),'')::uuid,retirement_reason='customer_confirmation_changed' WHERE customer_decision_id=NEW.id AND organization_id=NEW.organization_id AND is_current;
  END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.orderdesk_unit_source_changed() FROM PUBLIC;
CREATE TRIGGER unit_line_changed AFTER UPDATE ON public.orders_draftorderline FOR EACH ROW EXECUTE FUNCTION public.orderdesk_unit_source_changed();
CREATE TRIGGER unit_customer_changed AFTER UPDATE ON public.customers_draftcustomerdecision FOR EACH ROW EXECUTE FUNCTION public.orderdesk_unit_source_changed();
CREATE FUNCTION public.orderdesk_unit_revision_changed() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF pg_trigger_depth()=1 THEN
  UPDATE public.orders_draftorder SET updated_at=clock_timestamp() WHERE id=NEW.draft_id AND organization_id=NEW.organization_id AND status='draft';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.orderdesk_unit_revision_changed() FROM PUBLIC;
CREATE TRIGGER unit_decision_revision AFTER INSERT OR UPDATE ON public.product_units_draftlineunitdecision FOR EACH ROW EXECUTE FUNCTION public.orderdesk_unit_revision_changed();
CREATE FUNCTION public.orderdesk_unit_snapshot_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF TG_OP<>'INSERT' OR (current_user='orderdesk_app' AND NEW.actor_id IS DISTINCT FROM NULLIF(current_setting('orderdesk.user_id',true),'')::uuid)
  OR NOT EXISTS(SELECT 1 FROM public.product_units_draftlineunitdecision d
   JOIN public.orders_draftorderline l ON l.id=d.line_id AND l.organization_id=d.organization_id AND l.order_id=d.draft_id
   JOIN public.orders_purchaseorder o ON o.id=NEW.order_id AND o.organization_id=d.organization_id AND o.status='draft' AND o.source_draft_id IS NULL
   JOIN public.orders_purchaseorderline ol ON ol.id=NEW.order_line_id AND ol.organization_id=d.organization_id AND ol.order_id=o.id
   WHERE d.id=NEW.decision_id AND d.organization_id=NEW.organization_id AND d.draft_id=NEW.draft_id AND d.line_id=NEW.draft_line_id AND d.is_current AND d.snapshot=NEW.payload
    AND d.snapshot->'reference'=public.orderdesk_unit_reference(d.line_id,d.policy_id,d.alias_id)
    AND (ol.line_number,ol.sku,ol.description,ol.quantity,ol.unit)=(l.position,l.catalogue_sku_snapshot,l.catalogue_description_snapshot,l.quantity,l.unit)) THEN
  RAISE EXCEPTION 'Invalid immutable unit snapshot' USING ERRCODE='23514'; END IF;
 NEW.created_at=clock_timestamp();
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.orderdesk_unit_snapshot_guard() FROM PUBLIC;
CREATE TRIGGER unit_snapshot_guard BEFORE INSERT OR UPDATE ON public.product_units_orderlineunitsnapshot FOR EACH ROW EXECUTE FUNCTION public.orderdesk_unit_snapshot_guard();
GRANT INSERT,UPDATE ON public.product_units_draftlineunitdecision TO orderdesk_app;
GRANT INSERT ON public.product_units_orderlineunitsnapshot TO orderdesk_app;
"""

REMOVE = """
REVOKE INSERT,UPDATE ON public.product_units_draftlineunitdecision FROM orderdesk_app;
REVOKE INSERT ON public.product_units_orderlineunitsnapshot FROM orderdesk_app;
DROP TRIGGER unit_snapshot_guard ON public.product_units_orderlineunitsnapshot;
DROP FUNCTION public.orderdesk_unit_snapshot_guard();
DROP TRIGGER unit_decision_revision ON public.product_units_draftlineunitdecision;
DROP FUNCTION public.orderdesk_unit_revision_changed();
DROP TRIGGER unit_customer_changed ON public.customers_draftcustomerdecision;
DROP TRIGGER unit_line_changed ON public.orders_draftorderline;
DROP FUNCTION public.orderdesk_unit_source_changed();
DROP TRIGGER unit_decision_guard ON public.product_units_draftlineunitdecision;
DROP FUNCTION public.orderdesk_unit_decision_guard();
DROP FUNCTION public.orderdesk_unit_amount_valid(jsonb,numeric,numeric,numeric,integer,integer,jsonb);
DROP FUNCTION public.orderdesk_unit_reference(uuid,uuid,uuid);
"""


class Migration(migrations.Migration):
    dependencies = [("product_units", "0001_initial")]
    operations = [migrations.RunSQL(INSTALL, REMOVE)]
