"""Atomic import receipts with forced RLS and completion-only runtime updates."""

import uuid

import django.core.validators
import django.db.models.deletion
import django.db.models.functions
import django.db.models.lookups
from django.conf import settings
from django.db import migrations, models


def require_postgresql(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        raise RuntimeError("The catalogue receipt migration requires PostgreSQL.")


ROLE_GUARD = """
DO $$
BEGIN
    IF current_user <> 'orderdesk_migrator' THEN
        RAISE EXCEPTION 'Run catalogue migrations as orderdesk_migrator';
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

# Frozen historical definitions. All interpolation is fixed SQL, never input.
RECEIPT_COLUMNS = """
id, organization_id, initiating_user_id, idempotency_key, request_fingerprint,
mode, contract_identifier, state, response_payload, created_at, completed_at
"""

TENANT_ADMIN_RULE = """
catalog_catalogimportreceipt.organization_id =
    NULLIF(pg_catalog.current_setting('orderdesk.organization_id', true), '')::uuid
AND EXISTS (
    SELECT 1
    FROM public.organizations_membership AS m
    JOIN public.organizations_organization AS o ON o.id = m.organization_id
    JOIN public.accounts_user AS u ON u.id = m.user_id
    WHERE m.organization_id = catalog_catalogimportreceipt.organization_id
      AND m.user_id =
          NULLIF(pg_catalog.current_setting('orderdesk.user_id', true), '')::uuid
      AND m.is_active AND m.role = 'admin' AND o.is_active AND u.is_active
)
"""

INITIATOR_RULE = """
initiating_user_id =
    NULLIF(pg_catalog.current_setting('orderdesk.user_id', true), '')::uuid
"""

INSTALL_BOUNDARY = f"""
ALTER TABLE public.catalog_catalogimportreceipt ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.catalog_catalogimportreceipt FORCE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.catalog_catalogimportreceipt FROM PUBLIC, orderdesk_app;
REVOKE ALL ({RECEIPT_COLUMNS}) ON TABLE public.catalog_catalogimportreceipt
    FROM PUBLIC, orderdesk_app;
GRANT SELECT, INSERT ON TABLE public.catalog_catalogimportreceipt TO orderdesk_app;
GRANT UPDATE (state, response_payload, completed_at)
    ON TABLE public.catalog_catalogimportreceipt TO orderdesk_app;

CREATE POLICY catalog_import_tenant_boundary ON public.catalog_catalogimportreceipt
    AS RESTRICTIVE FOR ALL TO orderdesk_app
    USING ({TENANT_ADMIN_RULE}) WITH CHECK ({TENANT_ADMIN_RULE});
CREATE POLICY catalog_import_admin_read ON public.catalog_catalogimportreceipt
    AS PERMISSIVE FOR SELECT TO orderdesk_app USING (true);
CREATE POLICY catalog_import_admin_insert ON public.catalog_catalogimportreceipt
    AS PERMISSIVE FOR INSERT TO orderdesk_app
    WITH CHECK ({INITIATOR_RULE} AND state = 'processing'
                AND response_payload IS NULL AND completed_at IS NULL);
CREATE POLICY catalog_import_admin_complete ON public.catalog_catalogimportreceipt
    AS PERMISSIVE FOR UPDATE TO orderdesk_app
    USING ({INITIATOR_RULE} AND state = 'processing')
    WITH CHECK ({INITIATOR_RULE} AND state = 'completed');
CREATE POLICY catalog_import_owner_maintenance ON public.catalog_catalogimportreceipt
    AS PERMISSIVE FOR ALL TO orderdesk_migrator
    USING (true) WITH CHECK (true);

CREATE FUNCTION public.catalog_import_require_completed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
AS $$
BEGIN
    -- Deferred INSERT events retain the original processing NEW value. Query
    -- the final row instead. The maintenance owner sees it despite forced RLS,
    -- including when transaction-local actor context has been cleared.
    IF EXISTS (
        SELECT 1 FROM public.catalog_catalogimportreceipt AS receipt
        WHERE receipt.id = NEW.id AND receipt.state <> 'completed'
    ) THEN
        RAISE EXCEPTION 'Catalogue import receipts must complete before commit'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'catalog_import_completed_at_commit',
                  TABLE = 'catalog_catalogimportreceipt', SCHEMA = 'public';
    END IF;
    RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION public.catalog_import_require_completed()
    FROM PUBLIC, orderdesk_app;

CREATE CONSTRAINT TRIGGER catalog_import_completed_at_commit
    AFTER INSERT OR UPDATE ON public.catalog_catalogimportreceipt
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION public.catalog_import_require_completed();
"""  # noqa: S608 -- Only fixed historical SQL constants interpolate.

REMOVE_BOUNDARY = f"""
DROP TRIGGER catalog_import_completed_at_commit
    ON public.catalog_catalogimportreceipt;
DROP FUNCTION public.catalog_import_require_completed();
REVOKE ALL ON TABLE public.catalog_catalogimportreceipt FROM orderdesk_app;
REVOKE ALL ({RECEIPT_COLUMNS}) ON TABLE public.catalog_catalogimportreceipt
    FROM orderdesk_app;
DROP POLICY catalog_import_owner_maintenance ON public.catalog_catalogimportreceipt;
DROP POLICY catalog_import_admin_complete ON public.catalog_catalogimportreceipt;
DROP POLICY catalog_import_admin_insert ON public.catalog_catalogimportreceipt;
DROP POLICY catalog_import_admin_read ON public.catalog_catalogimportreceipt;
DROP POLICY catalog_import_tenant_boundary ON public.catalog_catalogimportreceipt;
ALTER TABLE public.catalog_catalogimportreceipt NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.catalog_catalogimportreceipt DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("catalog", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(require_postgresql, require_postgresql),
        migrations.RunSQL(ROLE_GUARD, reverse_sql=migrations.RunSQL.noop),
        migrations.CreateModel(
            name="CatalogImportReceipt",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("idempotency_key", models.UUIDField()),
                (
                    "request_fingerprint",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                "^[0-9a-f]{64}$", "Use a SHA-256 fingerprint."
                            )
                        ],
                    ),
                ),
                ("mode", models.CharField(default="create_only", max_length=20)),
                (
                    "contract_identifier",
                    models.CharField(
                        default="catalogue-create-only-csv-v1", max_length=40
                    ),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("processing", "Processing"),
                            ("completed", "Completed"),
                        ],
                        default="processing",
                        max_length=10,
                    ),
                ),
                ("response_payload", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="catalog_import_receipts",
                        to="organizations.organization",
                    ),
                ),
                (
                    "initiating_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="catalog_import_receipts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "idempotency_key"),
                        name="catalog_import_org_key_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(mode="create_only"),
                        name="catalog_import_create_only_mode",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            contract_identifier="catalogue-create-only-csv-v1"
                        ),
                        name="catalog_import_contract_identifier",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(request_fingerprint__regex="^[0-9a-f]{64}$"),
                        name="catalog_import_fingerprint_sha256",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                state="processing",
                                response_payload__isnull=True,
                                completed_at__isnull=True,
                            )
                            | models.Q(
                                state="completed",
                                response_payload__isnull=False,
                                completed_at__isnull=False,
                            )
                        ),
                        name="catalog_import_completion_shape",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(completed_at__isnull=True)
                            | models.Q(completed_at__gte=models.F("created_at"))
                        ),
                        name="catalog_import_completion_time",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(response_payload__isnull=True)
                            | django.db.models.lookups.Exact(
                                models.Func(
                                    "response_payload",
                                    function="jsonb_typeof",
                                    output_field=models.CharField(),
                                ),
                                "object",
                            )
                        ),
                        name="catalog_import_response_object",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(response_payload__isnull=True)
                            | django.db.models.lookups.LessThanOrEqual(
                                models.Func(
                                    django.db.models.functions.Cast(
                                        "response_payload",
                                        output_field=models.TextField(),
                                    ),
                                    function="octet_length",
                                    output_field=models.IntegerField(),
                                ),
                                8_388_608,
                            )
                        ),
                        name="catalog_import_response_size",
                    ),
                ]
            },
        ),
        migrations.RunSQL(INSTALL_BOUNDARY, reverse_sql=REMOVE_BOUNDARY),
    ]
