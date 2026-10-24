"""Fixed SQL for the initial controlled-reference boundary; migration-owned."""

from importlib import import_module

base = import_module("apps.orders.migrations.0005_order_tenant_boundary")
TABLES = (
    ("controlledunit", "unit_ref"),
    ("productunitpolicy", "unit_policy"),
    ("customerproductalias", "product_alias"),
    ("unitreferencereceipt", "unit_receipt"),
    ("draftlineunitdecision", "unit_decision"),
    ("orderlineunitsnapshot", "unit_snapshot"),
)

INSTALL = "\n".join(
    base.rls_statements("product_units_" + table, prefix).replace(
        "m.role IN ('admin', 'reviewer')",
        "m.role IN ('admin', 'reviewer', 'processor')" if table == "draftlineunitdecision" else "m.role = 'admin'",
    )
    for table, prefix in TABLES
) + """
REVOKE UPDATE ON public.product_units_unitreferencereceipt, public.product_units_orderlineunitsnapshot FROM orderdesk_app;
ALTER TABLE public.product_units_productunitpolicy
 ADD CONSTRAINT unit_policy_product_fk FOREIGN KEY(catalogue_item_id,organization_id) REFERENCES public.catalog_catalogitem(id,organization_id) DEFERRABLE INITIALLY IMMEDIATE,
 ADD CONSTRAINT unit_policy_requested_fk FOREIGN KEY(requested_unit_id,organization_id) REFERENCES public.product_units_controlledunit(id,organization_id) DEFERRABLE INITIALLY IMMEDIATE,
 ADD CONSTRAINT unit_policy_selling_fk FOREIGN KEY(selling_unit_id,organization_id) REFERENCES public.product_units_controlledunit(id,organization_id) DEFERRABLE INITIALLY IMMEDIATE,
 ADD CONSTRAINT unit_policy_destination_fk FOREIGN KEY(destination_unit_id,organization_id) REFERENCES public.product_units_controlledunit(id,organization_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE public.product_units_customerproductalias
 ADD CONSTRAINT product_alias_customer_fk FOREIGN KEY(customer_id,organization_id) REFERENCES public.customers_customeraccount(id,organization_id) DEFERRABLE INITIALLY IMMEDIATE,
 ADD CONSTRAINT product_alias_product_fk FOREIGN KEY(catalogue_item_id,organization_id) REFERENCES public.catalog_catalogitem(id,organization_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE public.product_units_unitreferencereceipt
 ADD CONSTRAINT unit_receipt_unit_fk FOREIGN KEY(unit_id,organization_id) REFERENCES public.product_units_controlledunit(id,organization_id) DEFERRABLE INITIALLY IMMEDIATE,
 ADD CONSTRAINT unit_receipt_policy_fk FOREIGN KEY(policy_id,organization_id) REFERENCES public.product_units_productunitpolicy(id,organization_id) DEFERRABLE INITIALLY IMMEDIATE,
 ADD CONSTRAINT unit_receipt_alias_fk FOREIGN KEY(alias_id,organization_id) REFERENCES public.product_units_customerproductalias(id,organization_id) DEFERRABLE INITIALLY IMMEDIATE;
"""
INSTALL += """
ALTER TABLE public.product_units_unitreferencereceipt ADD CONSTRAINT unit_receipt_json CHECK(jsonb_typeof(response)='object' AND octet_length(response::text)<=16384);
ALTER TABLE public.product_units_draftlineunitdecision
 ADD CONSTRAINT unit_decision_line_fk FOREIGN KEY(line_id,organization_id,draft_id) REFERENCES public.orders_draftorderline(id,organization_id,order_id) DEFERRABLE INITIALLY IMMEDIATE,
 ADD CONSTRAINT unit_decision_policy_fk FOREIGN KEY(policy_id,organization_id,catalogue_item_id) REFERENCES public.product_units_productunitpolicy(id,organization_id,catalogue_item_id) DEFERRABLE INITIALLY IMMEDIATE,
 ADD CONSTRAINT unit_decision_alias_fk FOREIGN KEY(alias_id,organization_id,customer_id,catalogue_item_id) REFERENCES public.product_units_customerproductalias(id,organization_id,customer_id,catalogue_item_id) DEFERRABLE INITIALLY IMMEDIATE,
 ADD CONSTRAINT unit_decision_customer_fk FOREIGN KEY(customer_decision_id,organization_id,draft_id,customer_id) REFERENCES public.customers_draftcustomerdecision(id,organization_id,draft_id,customer_id) DEFERRABLE INITIALLY IMMEDIATE,
 ADD CONSTRAINT unit_decision_json CHECK(jsonb_typeof(snapshot)='object' AND jsonb_typeof(request)='object' AND octet_length(snapshot::text)<=16384 AND octet_length(request::text)<=8192);
ALTER TABLE public.product_units_orderlineunitsnapshot
 ADD CONSTRAINT unit_snapshot_line_fk FOREIGN KEY(order_line_id,organization_id,order_id) REFERENCES public.orders_purchaseorderline(id,organization_id,order_id) DEFERRABLE INITIALLY IMMEDIATE,
 ADD CONSTRAINT unit_snapshot_decision_fk FOREIGN KEY(decision_id,organization_id,draft_id,draft_line_id) REFERENCES public.product_units_draftlineunitdecision(id,organization_id,draft_id,line_id) DEFERRABLE INITIALLY IMMEDIATE,
 ADD CONSTRAINT unit_snapshot_json CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=16384);
CREATE FUNCTION public.orderdesk_unit_reference_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF TG_OP='INSERT' AND TG_TABLE_NAME='product_units_customerproductalias' THEN
  IF EXISTS(SELECT 1 FROM public.catalog_catalogitem c WHERE c.organization_id=NEW.organization_id
   AND c.sku=NEW.value AND c.id<>NEW.catalogue_item_id) THEN
   RAISE EXCEPTION 'Alias collides with another stable SKU' USING ERRCODE='23514'; END IF;
 END IF;
 IF current_user='orderdesk_app' AND (NEW.updated_by_id IS DISTINCT FROM NULLIF(current_setting('orderdesk.user_id',true),'')::uuid
   OR (TG_OP='INSERT' AND NEW.created_by_id IS DISTINCT FROM NULLIF(current_setting('orderdesk.user_id',true),'')::uuid)) THEN
  RAISE EXCEPTION 'Invalid unit-reference actor' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (NEW.id,NEW.organization_id,NEW.created_by_id,NEW.created_at) IS DISTINCT FROM
     (OLD.id,OLD.organization_id,OLD.created_by_id,OLD.created_at) THEN
   RAISE EXCEPTION 'Unit-reference identity is immutable' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='product_units_controlledunit' THEN
   IF NEW.code IS DISTINCT FROM OLD.code THEN RAISE EXCEPTION 'Unit code is immutable' USING ERRCODE='23514'; END IF;
  ELSE
   IF NOT OLD.is_active OR NEW.is_active OR to_jsonb(NEW)-ARRAY['is_active','retirement_reason','updated_at','updated_by_id']
     IS DISTINCT FROM to_jsonb(OLD)-ARRAY['is_active','retirement_reason','updated_at','updated_by_id'] THEN
    RAISE EXCEPTION 'Retire an approval before explicitly replacing it' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 NEW.updated_at=clock_timestamp();
 IF TG_OP='INSERT' THEN NEW.created_at=NEW.updated_at; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.orderdesk_unit_reference_guard() FROM PUBLIC;
CREATE FUNCTION public.orderdesk_unit_receipt_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF TG_OP<>'INSERT' OR (current_user='orderdesk_app' AND NEW.actor_id IS DISTINCT FROM NULLIF(current_setting('orderdesk.user_id',true),'')::uuid) THEN
  RAISE EXCEPTION 'Invalid immutable unit-reference receipt' USING ERRCODE='23514'; END IF;
 NEW.created_at=clock_timestamp();
 IF NEW.response->>'id' IS DISTINCT FROM COALESCE(NEW.unit_id,NEW.policy_id,NEW.alias_id)::text
 OR NEW.response->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
 OR NEW.response->>'operation_key' IS DISTINCT FROM NEW.operation_key::text THEN
  RAISE EXCEPTION 'Invalid reference receipt source' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.orderdesk_unit_receipt_guard() FROM PUBLIC;
CREATE TRIGGER unit_receipt_guard BEFORE INSERT OR UPDATE ON public.product_units_unitreferencereceipt FOR EACH ROW EXECUTE FUNCTION public.orderdesk_unit_receipt_guard();
""" + "\n".join(
    f"CREATE TRIGGER unit_reference_guard BEFORE INSERT OR UPDATE ON public.product_units_{table} FOR EACH ROW EXECUTE FUNCTION public.orderdesk_unit_reference_guard();"
    for table in ("controlledunit", "productunitpolicy", "customerproductalias")
)

# Decision/snapshot writes remain denied until their explicit workflow guard is
# installed. No live application path can create an unprotected decision.
INSTALL += """
REVOKE INSERT,UPDATE ON public.product_units_draftlineunitdecision FROM orderdesk_app;
REVOKE INSERT ON public.product_units_orderlineunitsnapshot FROM orderdesk_app;
"""

REMOVE = """
DROP TRIGGER unit_receipt_guard ON public.product_units_unitreferencereceipt;
DROP FUNCTION public.orderdesk_unit_receipt_guard();
""" + "\n".join(
    f"DROP TRIGGER unit_reference_guard ON public.product_units_{table};"
    for table in ("controlledunit", "productunitpolicy", "customerproductalias")
) + "\nDROP FUNCTION public.orderdesk_unit_reference_guard();\n"
# Tables and their constraints/policies are removed by the CreateModel reversals.
