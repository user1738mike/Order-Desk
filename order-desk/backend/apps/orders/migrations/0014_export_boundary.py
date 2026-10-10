"""Forced artifact RLS, immutable source, claims and approved decision guards."""
from importlib import import_module
from django.db import migrations

boundary = import_module("apps.orders.migrations.0005_order_tenant_boundary")
INSTALL = boundary.rls_statements("orders_purchaseorderexport", "export") + """
REVOKE UPDATE ON public.orders_purchaseorderexport FROM orderdesk_app;
GRANT UPDATE (status, attempts, claim_token, lease_expires_at, generated_by_id,
 storage_key, size_bytes, sha256, error_code, completed_at, updated_at)
 ON public.orders_purchaseorderexport TO orderdesk_app;
ALTER POLICY export_member_read ON public.orders_purchaseorderexport
 USING (EXISTS (SELECT 1 FROM public.organizations_membership m
 WHERE m.organization_id=orders_purchaseorderexport.organization_id AND m.is_active
 AND m.role IN ('admin','reviewer') AND m.user_id=
 NULLIF(current_setting('orderdesk.user_id',true),'')::uuid));
ALTER TABLE public.orders_purchaseorderexport ADD CONSTRAINT export_order_org_fk
 FOREIGN KEY (order_id,organization_id) REFERENCES public.orders_purchaseorder(id,organization_id)
 DEFERRABLE INITIALLY IMMEDIATE,
 ADD CONSTRAINT export_payload_bounded CHECK (jsonb_typeof(payload)='object'
 AND octet_length(payload::text)<=8388608),
 ADD CONSTRAINT export_state_valid CHECK (
 (status='running' AND claim_token IS NOT NULL AND lease_expires_at IS NOT NULL
 AND storage_key='' AND size_bytes=0 AND sha256='' AND completed_at IS NULL AND error_code='')
 OR (status='failed' AND claim_token IS NULL AND lease_expires_at IS NULL
 AND storage_key='' AND size_bytes=0 AND sha256='' AND completed_at IS NULL
 AND error_code='generation_unavailable')
 OR (status='succeeded' AND claim_token IS NULL AND lease_expires_at IS NULL
 AND storage_key ~ '^exports/[0-9a-f]{32}$' AND size_bytes BETWEEN 1 AND 2097152
 AND sha256 ~ '^[0-9a-f]{64}$' AND completed_at IS NOT NULL AND error_code=''));
CREATE FUNCTION public.export_source_guard() RETURNS trigger LANGUAGE plpgsql
 SECURITY INVOKER SET search_path=pg_catalog,public AS $$
DECLARE expected jsonb;
BEGIN
 IF TG_OP='DELETE' AND current_user='orderdesk_migrator' THEN RETURN OLD; END IF;
 IF TG_OP='UPDATE' THEN
  IF OLD.status='succeeded' OR ROW(NEW.id,NEW.organization_id,NEW.order_id,NEW.profile,
   NEW.source_revision,NEW.payload,NEW.created_by_id,NEW.created_at) IS DISTINCT FROM
   ROW(OLD.id,OLD.organization_id,OLD.order_id,OLD.profile,OLD.source_revision,
   OLD.payload,OLD.created_by_id,OLD.created_at) THEN
   RAISE EXCEPTION 'Immutable export source' USING ERRCODE='23514'; END IF;
  IF NEW.status='running' THEN
   IF NEW.attempts<>OLD.attempts+1 OR NEW.claim_token=OLD.claim_token OR
    (OLD.status='running' AND OLD.lease_expires_at>statement_timestamp()) THEN
    RAISE EXCEPTION 'Invalid export claim' USING ERRCODE='23514'; END IF;
  ELSIF OLD.status<>'running' OR NEW.attempts<>OLD.attempts OR
   NEW.generated_by_id<>OLD.generated_by_id OR
   (NEW.status='succeeded' AND OLD.lease_expires_at<=statement_timestamp()) THEN
   RAISE EXCEPTION 'Invalid export publication' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_OP='INSERT' AND (NEW.status<>'running' OR NEW.attempts<>1) THEN
  RAISE EXCEPTION 'Invalid first export claim' USING ERRCODE='23514'; END IF;
 IF current_user='orderdesk_app' AND (NEW.generated_by_id IS DISTINCT FROM
  NULLIF(current_setting('orderdesk.user_id',true),'')::uuid OR
  (TG_OP='INSERT' AND NEW.created_by_id IS DISTINCT FROM NEW.generated_by_id)) THEN
  RAISE EXCEPTION 'Invalid export actor' USING ERRCODE='23514'; END IF;
 IF NEW.status<>'failed' THEN
  SELECT jsonb_build_object('order_id',o.id::text,'source_draft_id',o.source_draft_id::text,
   'order_number',o.purchase_order_number,'order_date',to_char(o.created_at AT TIME ZONE 'UTC','YYYY-MM-DD'),
   'customer_name',o.customer_name,'lines',COALESCE((SELECT jsonb_agg(jsonb_build_object(
    'id',l.id::text,'line_number',l.line_number,'sku',l.sku,'description',l.description,
    'quantity',l.quantity::text,'unit',l.unit) ORDER BY l.line_number,l.id)
    FROM public.orders_purchaseorderline l WHERE l.order_id=o.id AND l.organization_id=o.organization_id),'[]'::jsonb))
   INTO expected FROM public.orders_purchaseorder o JOIN public.orders_draftorder d
   ON d.id=o.source_draft_id AND d.organization_id=o.organization_id AND d.status='converted'
   WHERE o.id=NEW.order_id AND o.organization_id=NEW.organization_id AND o.is_active AND o.status='approved';
  IF expected IS NULL OR NEW.payload IS DISTINCT FROM expected OR NEW.source_revision<>
   encode(sha256(convert_to(NEW.payload::text,'UTF8')),'hex') THEN
   RAISE EXCEPTION 'Invalid approved export source' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.export_source_guard() FROM PUBLIC;
CREATE TRIGGER export_source_guard BEFORE INSERT OR UPDATE OR DELETE
 ON public.orders_purchaseorderexport FOR EACH ROW EXECUTE FUNCTION public.export_source_guard();
CREATE FUNCTION public.approved_conversion_guard() RETURNS trigger LANGUAGE plpgsql
 SECURITY INVOKER SET search_path=pg_catalog,public AS $$
BEGIN
 IF OLD.source_draft_id IS NOT NULL AND OLD.status='approved' AND
 ROW(NEW.status,NEW.reviewed_by_id,NEW.reviewed_at,NEW.review_note) IS DISTINCT FROM
 ROW(OLD.status,OLD.reviewed_by_id,OLD.reviewed_at,OLD.review_note) THEN
 RAISE EXCEPTION 'Approved conversion decision is immutable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.approved_conversion_guard() FROM PUBLIC;
CREATE TRIGGER approved_conversion_guard BEFORE UPDATE ON public.orders_purchaseorder
 FOR EACH ROW EXECUTE FUNCTION public.approved_conversion_guard();
"""
# Explicit reverse keeps historical table boundaries untouched.
REMOVE = """
DROP TRIGGER approved_conversion_guard ON public.orders_purchaseorder;
DROP FUNCTION public.approved_conversion_guard();
DROP TRIGGER export_source_guard ON public.orders_purchaseorderexport;
DROP FUNCTION public.export_source_guard();
ALTER TABLE public.orders_purchaseorderexport DROP CONSTRAINT export_order_org_fk,
 DROP CONSTRAINT export_payload_bounded, DROP CONSTRAINT export_state_valid;
REVOKE ALL ON public.orders_purchaseorderexport FROM orderdesk_app;
DROP POLICY export_tenant_boundary ON public.orders_purchaseorderexport;
DROP POLICY export_member_read ON public.orders_purchaseorderexport;
DROP POLICY export_reviewer_insert ON public.orders_purchaseorderexport;
DROP POLICY export_reviewer_update ON public.orders_purchaseorderexport;
DROP POLICY export_owner_maintenance ON public.orders_purchaseorderexport;
ALTER TABLE public.orders_purchaseorderexport NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.orders_purchaseorderexport DISABLE ROW LEVEL SECURITY;
"""

class Migration(migrations.Migration):
    dependencies = [("orders", "0013_purchase_order_exports")]
    operations = [
        migrations.RunPython(boundary.require_postgresql, boundary.require_postgresql),
        migrations.RunSQL(boundary.ROLE_GUARD, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(INSTALL, reverse_sql=REMOVE),
    ]
