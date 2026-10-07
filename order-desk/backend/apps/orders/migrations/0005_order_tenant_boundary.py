"""Harden the existing intake tables without rewriting applied migrations."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from psycopg import sql


def require_postgresql(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        raise RuntimeError("The order tenant-boundary migration requires PostgreSQL.")


ROLE_GUARD = """
DO $$
BEGIN
    IF current_user <> 'orderdesk_migrator' THEN
        RAISE EXCEPTION 'Run order migrations as orderdesk_migrator';
    END IF;
    IF (SELECT count(*) FROM pg_catalog.pg_roles
        WHERE rolname IN ('orderdesk_app', 'orderdesk_migrator')) <> 2 THEN
        RAISE EXCEPTION 'Provision the two Order Desk database roles first';
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
    ) OR pg_catalog.has_schema_privilege('orderdesk_app', 'public', 'CREATE') THEN
        RAISE EXCEPTION 'Unsafe Order Desk database role configuration';
    END IF;
END;
$$;
"""


def validate_existing_rows(apps, schema_editor):
    # Fail before adding constraints: never silently repair tenant associations,
    # invent a historical reviewer, discard duplicate reviews, or remove data.
    checks = (
        (
            """
            SELECT 1 FROM public.orders_purchaseorder
            WHERE status NOT IN ('draft', 'pending_review', 'approved', 'rejected')
               OR (status IN ('draft', 'pending_review')
                   AND (reviewed_by_id IS NOT NULL OR reviewed_at IS NOT NULL))
               OR (status IN ('approved', 'rejected')
                   AND (reviewed_by_id IS NULL OR reviewed_at IS NULL))
            LIMIT 1
            """,
            "Existing purchase-order status/reviewer metadata is inconsistent. "
            "Correct the records through an explicit, reviewed data repair "
            "before retrying.",
        ),
        (
            """
            SELECT 1 FROM public.orders_orderdocument AS d
            JOIN public.orders_purchaseorder AS o ON o.id = d.order_id
            WHERE d.organization_id <> o.organization_id
            LIMIT 1
            """,
            "Existing source documents reference orders in another organization. "
            "Review and repair the tenant associations explicitly before retrying.",
        ),
        (
            """
            SELECT 1 FROM public.orders_orderdocument
            WHERE status NOT IN ('received', 'pending_review', 'rejected')
            LIMIT 1
            """,
            "Existing source documents contain unsupported status values. "
            "Review those records before retrying.",
        ),
        (
            """
            SELECT 1 FROM public.orders_orderdocumentreview AS r
            JOIN public.orders_orderdocument AS d ON d.id = r.document_id
            WHERE r.organization_id <> d.organization_id
            LIMIT 1
            """,
            "Existing document reviews reference documents in another organization. "
            "Review and repair the tenant associations explicitly before retrying.",
        ),
        (
            """
            SELECT 1 FROM public.orders_orderdocumentreview
            WHERE status NOT IN ('needs_review', 'accepted', 'rejected')
            LIMIT 1
            """,
            "Existing document reviews contain unsupported status values. "
            "Review those records before retrying.",
        ),
        (
            """
            SELECT 1 FROM public.orders_orderdocumentreview
            WHERE status IN ('accepted', 'rejected')
            LIMIT 1
            """,
            "Completed document reviews predate recorded resolver identity/time. "
            "This migration cannot invent that provenance. Prepare an explicit "
            "reviewed data migration for those historical records before retrying.",
        ),
        (
            """
            SELECT 1 FROM public.orders_orderdocumentreview
            WHERE status = 'needs_review'
            GROUP BY document_id HAVING count(*) > 1
            LIMIT 1
            """,
            "Existing documents have multiple pending extraction reviews. "
            "Resolve the duplicates through a reviewed data repair before retrying.",
        ),
    )
    with schema_editor.connection.cursor() as cursor:
        for query, message in checks:
            cursor.execute(query)
            if cursor.fetchone() is not None:
                raise RuntimeError(message)


BACKFILL_LINE_ORGANIZATIONS = """
UPDATE public.orders_purchaseorderline AS line
SET organization_id = parent.organization_id
FROM public.orders_purchaseorder AS parent
WHERE parent.id = line.order_id;
"""

INSTALL_PARENT_CONSTRAINTS = """
ALTER TABLE public.orders_purchaseorderline
    ADD CONSTRAINT orderline_order_org_fk
    FOREIGN KEY (order_id, organization_id)
    REFERENCES public.orders_purchaseorder (id, organization_id)
    DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE public.orders_orderdocument
    ADD CONSTRAINT orderdocument_order_org_fk
    FOREIGN KEY (order_id, organization_id)
    REFERENCES public.orders_purchaseorder (id, organization_id)
    DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE public.orders_orderdocumentreview
    ADD CONSTRAINT orderreview_document_org_fk
    FOREIGN KEY (document_id, organization_id)
    REFERENCES public.orders_orderdocument (id, organization_id)
    DEFERRABLE INITIALLY IMMEDIATE;
"""

REMOVE_PARENT_CONSTRAINTS = """
ALTER TABLE public.orders_orderdocumentreview
    DROP CONSTRAINT orderreview_document_org_fk;
ALTER TABLE public.orders_orderdocument DROP CONSTRAINT orderdocument_order_org_fk;
ALTER TABLE public.orders_purchaseorderline DROP CONSTRAINT orderline_order_org_fk;
"""

# Fixed, migration-local SQL identifiers; no caller-controlled SQL fragments.
TABLES = (
    ("orders_purchaseorder", "order"),
    ("orders_purchaseorderline", "orderline"),
    ("orders_orderdocument", "orderdocument"),
    ("orders_orderdocumentreview", "orderreview"),
)


def rls_statements(table, prefix):
    tenant_rule = (
        sql.SQL("""
    {table}.organization_id =
        NULLIF(pg_catalog.current_setting('orderdesk.organization_id', true), '')::uuid
    AND EXISTS (
        SELECT 1
        FROM public.organizations_membership AS m
        JOIN public.organizations_organization AS o ON o.id = m.organization_id
        JOIN public.accounts_user AS u ON u.id = m.user_id
        WHERE m.organization_id = {table}.organization_id
          AND m.user_id =
              NULLIF(pg_catalog.current_setting('orderdesk.user_id', true), '')::uuid
          AND m.is_active AND o.is_active AND u.is_active
    )
    """)
        .format(table=sql.Identifier(table))
        .as_string()
    )
    reviewer_rule = (
        sql.SQL("""
    EXISTS (
        SELECT 1 FROM public.organizations_membership AS m
        WHERE m.organization_id = {table}.organization_id
          AND m.user_id =
              NULLIF(pg_catalog.current_setting('orderdesk.user_id', true), '')::uuid
          AND m.is_active AND m.role IN ('admin', 'reviewer')
    )
    """)
        .format(table=sql.Identifier(table))
        .as_string()
    )
    return f"""
    ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;
    REVOKE ALL ON TABLE public.{table} FROM PUBLIC, orderdesk_app;
    GRANT SELECT, INSERT, UPDATE ON TABLE public.{table} TO orderdesk_app;

    CREATE POLICY {prefix}_tenant_boundary ON public.{table}
        AS RESTRICTIVE FOR ALL TO orderdesk_app
        USING ({tenant_rule}) WITH CHECK ({tenant_rule});
    CREATE POLICY {prefix}_member_read ON public.{table}
        AS PERMISSIVE FOR SELECT TO orderdesk_app USING (true);
    CREATE POLICY {prefix}_reviewer_insert ON public.{table}
        AS PERMISSIVE FOR INSERT TO orderdesk_app WITH CHECK ({reviewer_rule});
    CREATE POLICY {prefix}_reviewer_update ON public.{table}
        AS PERMISSIVE FOR UPDATE TO orderdesk_app
        USING ({reviewer_rule}) WITH CHECK ({reviewer_rule});
    CREATE POLICY {prefix}_owner_maintenance ON public.{table}
        AS PERMISSIVE FOR ALL TO orderdesk_migrator
        USING (true) WITH CHECK (true);
    """


INSTALL_RLS = "\n".join(rls_statements(table, prefix) for table, prefix in TABLES)
REMOVE_RLS = "\n".join(
    f"""
    REVOKE ALL ON TABLE public.{table} FROM orderdesk_app;
    DROP POLICY {prefix}_owner_maintenance ON public.{table};
    DROP POLICY {prefix}_reviewer_update ON public.{table};
    DROP POLICY {prefix}_reviewer_insert ON public.{table};
    DROP POLICY {prefix}_member_read ON public.{table};
    DROP POLICY {prefix}_tenant_boundary ON public.{table};
    ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY;
    ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;
    """
    for table, prefix in reversed(TABLES)
)


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("orders", "0004_orderdocumentreview"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(require_postgresql, require_postgresql),
        migrations.RunSQL(ROLE_GUARD, reverse_sql=migrations.RunSQL.noop),
        migrations.RunPython(validate_existing_rows, migrations.RunPython.noop),
        migrations.AddField(
            model_name="purchaseorderline",
            name="organization",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="purchase_order_lines",
                to="organizations.organization",
            ),
        ),
        migrations.RunSQL(
            BACKFILL_LINE_ORGANIZATIONS, reverse_sql=migrations.RunSQL.noop
        ),
        migrations.AlterField(
            model_name="purchaseorderline",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="purchase_order_lines",
                to="organizations.organization",
            ),
        ),
        migrations.AlterField(
            model_name="purchaseorder",
            name="reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reviewed_purchase_orders",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="orderdocumentreview",
            name="resolved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="resolved_order_document_reviews",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="orderdocumentreview",
            name="resolved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="purchaseorder",
            constraint=models.UniqueConstraint(
                fields=("id", "organization"), name="purchaseorder_id_org_unique"
            ),
        ),
        migrations.AddConstraint(
            model_name="purchaseorder",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    status__in=["draft", "pending_review", "approved", "rejected"]
                ),
                name="purchaseorder_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="purchaseorder",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        status__in=("draft", "pending_review"),
                        reviewed_by__isnull=True,
                        reviewed_at__isnull=True,
                    )
                    | models.Q(
                        status__in=("approved", "rejected"),
                        reviewed_by__isnull=False,
                        reviewed_at__isnull=False,
                    )
                ),
                name="purchaseorder_review_metadata_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderdocument",
            constraint=models.UniqueConstraint(
                fields=("id", "organization"), name="orderdocument_id_org_unique"
            ),
        ),
        migrations.AddConstraint(
            model_name="orderdocument",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    status__in=["received", "pending_review", "rejected"]
                ),
                name="orderdocument_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderdocumentreview",
            constraint=models.CheckConstraint(
                condition=models.Q(status__in=["needs_review", "accepted", "rejected"]),
                name="orderreview_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderdocumentreview",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        status="needs_review",
                        resolved_by__isnull=True,
                        resolved_at__isnull=True,
                    )
                    | models.Q(
                        status__in=("accepted", "rejected"),
                        resolved_by__isnull=False,
                        resolved_at__isnull=False,
                    )
                ),
                name="orderreview_resolution_metadata_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderdocumentreview",
            constraint=models.UniqueConstraint(
                fields=("document",),
                condition=models.Q(status="needs_review"),
                name="orderreview_one_pending_per_doc",
            ),
        ),
        migrations.RunSQL(
            INSTALL_PARENT_CONSTRAINTS, reverse_sql=REMOVE_PARENT_CONSTRAINTS
        ),
        migrations.RunSQL(INSTALL_RLS, reverse_sql=REMOVE_RLS),
    ]
