"""Composite tenant references and forced RLS for manual draft intake."""

from django.db import migrations


def require_postgresql(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        raise RuntimeError("Draft-order tenant boundaries require PostgreSQL.")


ROLE_GUARD = """
DO $$
BEGIN
    IF current_user <> 'orderdesk_migrator' THEN
        RAISE EXCEPTION 'Run order migrations as orderdesk_migrator';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname IN ('orderdesk_app', 'orderdesk_migrator')
          AND (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole
               OR rolinherit OR rolreplication)
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members AS m
        JOIN pg_catalog.pg_roles AS r ON r.oid = m.member
        WHERE r.rolname IN ('orderdesk_app', 'orderdesk_migrator')
    ) OR (SELECT count(*) FROM pg_catalog.pg_roles
          WHERE rolname IN ('orderdesk_app', 'orderdesk_migrator')) <> 2
      OR pg_catalog.has_schema_privilege('orderdesk_app', 'public', 'CREATE') THEN
        RAISE EXCEPTION 'Unsafe Order Desk database roles';
    END IF;
END;
$$;
"""

INSTALL_REFERENCES = """
ALTER TABLE public.orders_draftorderline
    ADD CONSTRAINT draftline_order_org_fk
    FOREIGN KEY (order_id, organization_id)
    REFERENCES public.orders_draftorder (id, organization_id)
    DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE public.orders_draftorderline
    ADD CONSTRAINT draftline_catalogue_org_fk
    FOREIGN KEY (catalogue_item_id, organization_id)
    REFERENCES public.catalog_catalogitem (id, organization_id)
    DEFERRABLE INITIALLY IMMEDIATE;
"""

REMOVE_REFERENCES = """
ALTER TABLE public.orders_draftorderline DROP CONSTRAINT draftline_catalogue_org_fk;
ALTER TABLE public.orders_draftorderline DROP CONSTRAINT draftline_order_org_fk;
"""


def tenant_rule(table):
    return f"""
    {table}.organization_id =
        NULLIF(pg_catalog.current_setting('orderdesk.organization_id', true), '')::uuid
    AND EXISTS (
        SELECT 1 FROM public.organizations_membership AS m
        JOIN public.organizations_organization AS o ON o.id = m.organization_id
        JOIN public.accounts_user AS u ON u.id = m.user_id
        WHERE m.organization_id = {table}.organization_id
          AND m.user_id =
              NULLIF(pg_catalog.current_setting('orderdesk.user_id', true), '')::uuid
          AND m.is_active AND o.is_active AND u.is_active
    )
    """


def write_rule(table):
    return f"""
    EXISTS (
        SELECT 1 FROM public.organizations_membership AS m
        WHERE m.organization_id = {table}.organization_id
          AND m.user_id =
              NULLIF(pg_catalog.current_setting('orderdesk.user_id', true), '')::uuid
          AND m.is_active AND m.role IN ('admin', 'reviewer')
    )
    """


HEADER_INSERT = """
orders_draftorder.initiating_user_id =
    NULLIF(pg_catalog.current_setting('orderdesk.user_id', true), '')::uuid
"""

LINE_PARENT = """
EXISTS (
    SELECT 1 FROM public.orders_draftorder AS parent
    WHERE parent.id = orders_draftorderline.order_id
      AND parent.organization_id = orders_draftorderline.organization_id
      AND parent.status = 'draft'
)
"""


def install_table(table, prefix, insert_extra="true", update_extra="true"):
    tenant = tenant_rule(table)
    writer = write_rule(table)
    return f"""
    ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;
    REVOKE ALL ON TABLE public.{table} FROM PUBLIC, orderdesk_app;
    GRANT SELECT, INSERT ON TABLE public.{table} TO orderdesk_app;

    CREATE POLICY {prefix}_tenant_boundary ON public.{table}
        AS RESTRICTIVE FOR ALL TO orderdesk_app
        USING ({tenant}) WITH CHECK ({tenant});
    CREATE POLICY {prefix}_member_read ON public.{table}
        AS PERMISSIVE FOR SELECT TO orderdesk_app USING (true);
    CREATE POLICY {prefix}_writer_insert ON public.{table}
        AS PERMISSIVE FOR INSERT TO orderdesk_app
        WITH CHECK ({writer} AND ({insert_extra}));
    CREATE POLICY {prefix}_writer_update ON public.{table}
        AS PERMISSIVE FOR UPDATE TO orderdesk_app
        USING ({writer} AND ({update_extra}))
        WITH CHECK ({writer} AND ({update_extra}));
    CREATE POLICY {prefix}_owner_maintenance ON public.{table}
        AS PERMISSIVE FOR ALL TO orderdesk_migrator
        USING (true) WITH CHECK (true);
    """


HEADER_COLUMNS = """
id, organization_id, initiating_user_id, status, source_type,
customer_name, customer_reference, original_intake_text, created_at, updated_at
"""
LINE_COLUMNS = """
id, organization_id, order_id, position, requested_sku,
requested_description, quantity, unit, catalogue_item_id,
catalogue_sku_snapshot, catalogue_description_snapshot, created_at, updated_at
"""

INSTALL_RLS = (
    install_table("orders_draftorder", "draftorder", HEADER_INSERT)
    + install_table("orders_draftorderline", "draftline", LINE_PARENT, LINE_PARENT)
    + f"""
    REVOKE ALL ({HEADER_COLUMNS}) ON TABLE public.orders_draftorder
        FROM PUBLIC, orderdesk_app;
    REVOKE ALL ({LINE_COLUMNS}) ON TABLE public.orders_draftorderline
        FROM PUBLIC, orderdesk_app;
    GRANT UPDATE (customer_name, customer_reference, original_intake_text, updated_at)
        ON TABLE public.orders_draftorder TO orderdesk_app;
    GRANT UPDATE (position, requested_sku, requested_description, quantity, unit,
                  catalogue_item_id, catalogue_sku_snapshot,
                  catalogue_description_snapshot, updated_at)
        ON TABLE public.orders_draftorderline TO orderdesk_app;
    """
)


def remove_table(table, prefix):
    return f"""
    REVOKE ALL ON TABLE public.{table} FROM orderdesk_app;
    DROP POLICY {prefix}_owner_maintenance ON public.{table};
    DROP POLICY {prefix}_writer_update ON public.{table};
    DROP POLICY {prefix}_writer_insert ON public.{table};
    DROP POLICY {prefix}_member_read ON public.{table};
    DROP POLICY {prefix}_tenant_boundary ON public.{table};
    ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY;
    ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;
    """


REMOVE_RLS = remove_table("orders_draftorderline", "draftline") + remove_table(
    "orders_draftorder", "draftorder"
)


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("orders", "0006_draftorder_draftorderline_and_more"),
        ("catalog", "0003_catalogitem_catalog_id_org_unique"),
    ]

    operations = [
        migrations.RunPython(require_postgresql, require_postgresql),
        migrations.RunSQL(ROLE_GUARD, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(INSTALL_REFERENCES, reverse_sql=REMOVE_REFERENCES),
        migrations.RunSQL(INSTALL_RLS, reverse_sql=REMOVE_RLS),
    ]
