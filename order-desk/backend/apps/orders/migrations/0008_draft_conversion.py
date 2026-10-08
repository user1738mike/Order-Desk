"""Unique tenant-consistent conversion linkage and immutable source snapshots."""

import django.db.models.deletion
from django.db import migrations, models


GUARD = """
DO $$ BEGIN
    IF current_user <> 'orderdesk_migrator' THEN
        RAISE EXCEPTION 'Run order migrations as orderdesk_migrator';
    END IF;
END $$;
"""

INSTALL = """
ALTER TABLE public.orders_purchaseorder ADD CONSTRAINT order_source_draft_org_fk
    FOREIGN KEY (source_draft_id, organization_id)
    REFERENCES public.orders_draftorder (id, organization_id)
    DEFERRABLE INITIALLY IMMEDIATE;
GRANT UPDATE (status) ON public.orders_draftorder TO orderdesk_app;

CREATE FUNCTION public.order_conversion_admin(organization uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog, public AS $$
    SELECT current_user = 'orderdesk_migrator' OR EXISTS (
        SELECT 1 FROM public.organizations_membership m
        JOIN public.organizations_organization o ON o.id = m.organization_id
        JOIN public.accounts_user u ON u.id = m.user_id
        WHERE m.organization_id = organization AND m.is_active
        AND o.is_active AND u.is_active AND m.role = 'admin'
        AND m.user_id = NULLIF(current_setting('orderdesk.user_id', true), '')::uuid
    );
$$;
REVOKE ALL ON FUNCTION public.order_conversion_admin(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.order_conversion_admin(uuid)
    TO orderdesk_app, orderdesk_migrator;

CREATE FUNCTION public.order_conversion_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
BEGIN
    -- Explicit maintenance deletion is needed for reviewed repair/fixture cleanup.
    IF TG_OP = 'DELETE' AND current_user = 'orderdesk_migrator' THEN RETURN OLD; END IF;
    IF TG_TABLE_NAME = 'orders_draftorder' THEN
        IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.status = 'converted' THEN
            RAISE EXCEPTION 'Converted source is immutable'
                USING ERRCODE = '23514', CONSTRAINT = 'converted_draft_immutable';
        END IF;
        IF TG_OP <> 'DELETE' AND NEW.status = 'converted'
           AND NOT public.order_conversion_admin(NEW.organization_id) THEN
            RAISE EXCEPTION 'Administrator conversion access required' USING ERRCODE = '42501';
        END IF;
    ELSIF TG_TABLE_NAME = 'orders_draftorderline' THEN
        IF EXISTS (SELECT 1 FROM public.orders_draftorder WHERE status = 'converted'
            AND (id = CASE WHEN TG_OP = 'DELETE' THEN OLD.order_id ELSE NEW.order_id END
                OR (TG_OP = 'UPDATE' AND id = OLD.order_id))) THEN
            RAISE EXCEPTION 'Converted source lines are immutable'
                USING ERRCODE = '23514', CONSTRAINT = 'converted_draft_immutable';
        END IF;
    ELSIF TG_TABLE_NAME = 'orders_purchaseorder' THEN
        IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.source_draft_id IS NOT NULL THEN
            IF TG_OP = 'DELETE' OR ROW(NEW.id, NEW.organization_id, NEW.created_by_id,
                NEW.created_at, NEW.customer_name, NEW.purchase_order_number, NEW.source_draft_id)
                IS DISTINCT FROM ROW(OLD.id, OLD.organization_id, OLD.created_by_id,
                OLD.created_at, OLD.customer_name, OLD.purchase_order_number, OLD.source_draft_id) THEN
                RAISE EXCEPTION 'Conversion snapshot is immutable'
                    USING ERRCODE = '23514', CONSTRAINT = 'conversion_snapshot_immutable';
            END IF;
        END IF;
        IF TG_OP <> 'DELETE' AND NEW.source_draft_id IS NOT NULL
           AND (TG_OP = 'INSERT' OR OLD.source_draft_id IS DISTINCT FROM NEW.source_draft_id) THEN
            IF NOT public.order_conversion_admin(NEW.organization_id)
               OR (current_user <> 'orderdesk_migrator' AND NEW.created_by_id IS DISTINCT FROM
                   NULLIF(current_setting('orderdesk.user_id', true), '')::uuid) THEN
                RAISE EXCEPTION 'Administrator conversion access required' USING ERRCODE = '42501';
            END IF;
            IF NEW.status <> 'draft' OR NOT NEW.is_active THEN
                RAISE EXCEPTION 'Conversion creates an active draft order'
                    USING ERRCODE = '23514', CONSTRAINT = 'draft_conversion_complete';
            END IF;
        END IF;
    ELSE
        IF EXISTS (SELECT 1 FROM public.orders_purchaseorder WHERE source_draft_id IS NOT NULL
            AND (id = CASE WHEN TG_OP = 'DELETE' THEN OLD.order_id ELSE NEW.order_id END
                OR (TG_OP = 'UPDATE' AND id = OLD.order_id))) THEN
            RAISE EXCEPTION 'Conversion lines are immutable'
                USING ERRCODE = '23514', CONSTRAINT = 'conversion_snapshot_immutable';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
REVOKE ALL ON FUNCTION public.order_conversion_guard() FROM PUBLIC;

CREATE TRIGGER draft_conversion_guard BEFORE INSERT OR UPDATE OR DELETE
    ON public.orders_draftorder FOR EACH ROW EXECUTE FUNCTION public.order_conversion_guard();
CREATE TRIGGER draft_line_conversion_guard BEFORE INSERT OR UPDATE OR DELETE
    ON public.orders_draftorderline FOR EACH ROW EXECUTE FUNCTION public.order_conversion_guard();
CREATE TRIGGER order_conversion_guard BEFORE INSERT OR UPDATE OR DELETE
    ON public.orders_purchaseorder FOR EACH ROW EXECUTE FUNCTION public.order_conversion_guard();
CREATE TRIGGER order_line_conversion_guard BEFORE INSERT OR UPDATE OR DELETE
    ON public.orders_purchaseorderline FOR EACH ROW EXECUTE FUNCTION public.order_conversion_guard();

CREATE FUNCTION public.order_conversion_complete() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE source_id uuid; source_row public.orders_draftorder;
        converted_row public.orders_purchaseorder;
BEGIN
    IF TG_TABLE_NAME = 'orders_draftorder' THEN source_id := NEW.id;
    ELSIF TG_OP = 'DELETE' THEN source_id := OLD.source_draft_id;
    ELSE source_id := NEW.source_draft_id; END IF;
    IF source_id IS NULL THEN RETURN NULL; END IF;
    SELECT * INTO source_row FROM public.orders_draftorder WHERE id = source_id;
    IF NOT FOUND THEN RETURN NULL; END IF;
    SELECT * INTO converted_row FROM public.orders_purchaseorder WHERE source_draft_id = source_id;
    IF (source_row.status = 'converted') <> FOUND THEN
        RAISE EXCEPTION 'Conversion linkage and status must commit together'
            USING ERRCODE = '23514', CONSTRAINT = 'draft_conversion_complete';
    END IF;
    IF source_row.status = 'converted' THEN
        IF converted_row.customer_name IS DISTINCT FROM source_row.customer_name
           OR NOT EXISTS (SELECT 1 FROM public.orders_draftorderline WHERE order_id = source_id)
           OR EXISTS (
                (SELECT position, catalogue_sku_snapshot, catalogue_description_snapshot, quantity, unit
                 FROM public.orders_draftorderline WHERE order_id = source_id
                 EXCEPT SELECT line_number, sku, description, quantity, unit
                 FROM public.orders_purchaseorderline WHERE order_id = converted_row.id)
                UNION ALL
                (SELECT line_number, sku, description, quantity, unit
                 FROM public.orders_purchaseorderline WHERE order_id = converted_row.id
                 EXCEPT SELECT position, catalogue_sku_snapshot, catalogue_description_snapshot, quantity, unit
                 FROM public.orders_draftorderline WHERE order_id = source_id)
           ) THEN
            RAISE EXCEPTION 'Conversion must contain the complete source snapshot'
                USING ERRCODE = '23514', CONSTRAINT = 'draft_conversion_complete';
        END IF;
    END IF;
    RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION public.order_conversion_complete() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER draft_conversion_complete AFTER INSERT OR UPDATE
    ON public.orders_draftorder DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION public.order_conversion_complete();
CREATE CONSTRAINT TRIGGER order_conversion_complete AFTER INSERT OR UPDATE OR DELETE
    ON public.orders_purchaseorder DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION public.order_conversion_complete();
"""

REMOVE = """
DROP TRIGGER order_conversion_complete ON public.orders_purchaseorder;
DROP TRIGGER draft_conversion_complete ON public.orders_draftorder;
DROP TRIGGER order_line_conversion_guard ON public.orders_purchaseorderline;
DROP TRIGGER order_conversion_guard ON public.orders_purchaseorder;
DROP TRIGGER draft_line_conversion_guard ON public.orders_draftorderline;
DROP TRIGGER draft_conversion_guard ON public.orders_draftorder;
DROP FUNCTION public.order_conversion_complete();
DROP FUNCTION public.order_conversion_guard();
DROP FUNCTION public.order_conversion_admin(uuid);
REVOKE UPDATE (status) ON public.orders_draftorder FROM orderdesk_app;
ALTER TABLE public.orders_purchaseorder DROP CONSTRAINT order_source_draft_org_fk;
"""


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("orders", "0007_draft_order_boundary")]
    operations = [
        migrations.RunSQL(GUARD, reverse_sql=migrations.RunSQL.noop),
        migrations.RemoveConstraint(model_name="draftorder", name="draftorder_status_draft"),
        migrations.AlterField(model_name="draftorder", name="status", field=models.CharField(
            choices=[("draft", "Draft"), ("converted", "Converted")], default="draft", max_length=16)),
        migrations.AddConstraint(model_name="draftorder", constraint=models.CheckConstraint(
            condition=models.Q(status__in=["draft", "converted"]), name="draftorder_status_valid")),
        migrations.AddField(model_name="purchaseorder", name="source_draft", field=models.OneToOneField(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
            related_name="converted_order", to="orders.draftorder")),
        migrations.RunSQL(INSTALL, reverse_sql=REMOVE),
    ]
