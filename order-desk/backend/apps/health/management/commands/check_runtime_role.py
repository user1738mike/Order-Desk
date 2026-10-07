"""Refuse API startup with a role that could bypass future tenant policies."""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Verify the connected role cannot administer or own application tables."

    def handle(self, *args, **options) -> None:
        if connection.vendor != "postgresql":
            raise CommandError("The runtime role check requires PostgreSQL.")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole,
                       has_schema_privilege(current_user, 'public', 'CREATE'),
                       EXISTS (
                           SELECT 1 FROM pg_class c
                           JOIN pg_namespace n ON n.oid = c.relnamespace
                           WHERE n.nspname = 'public'
                             AND c.relowner = (SELECT oid FROM pg_roles
                                               WHERE rolname = current_user)
                       ),
                       EXISTS (
                           SELECT 1 FROM pg_auth_members m
                           WHERE m.member = (SELECT oid FROM pg_roles
                                              WHERE rolname = current_user)
                       ),
                       EXISTS (
                           SELECT 1 FROM pg_class c
                           JOIN pg_namespace n ON n.oid = c.relnamespace
                           WHERE n.nspname = 'public'
                             AND c.relname = 'catalog_catalogimportreceipt'
                             AND (
                               NOT c.relrowsecurity OR NOT c.relforcerowsecurity
                               OR NOT has_table_privilege(current_user, c.oid, 'SELECT')
                               OR NOT has_table_privilege(current_user, c.oid, 'INSERT')
                               OR has_table_privilege(
                                   current_user, c.oid,
                                   'UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN'
                               )
                               OR EXISTS (
                                   SELECT 1 FROM unnest(ARRAY[
                                       'state', 'response_payload', 'completed_at'
                                   ]) AS allowed(column_name)
                                   WHERE NOT has_column_privilege(
                                       current_user, c.oid,
                                       allowed.column_name, 'UPDATE'
                                   )
                               )
                               OR EXISTS (
                                   SELECT 1 FROM unnest(ARRAY[
                                       'id', 'organization_id', 'initiating_user_id',
                                       'idempotency_key', 'request_fingerprint',
                                       'mode', 'contract_identifier', 'created_at'
                                   ]) AS fixed(column_name)
                                   WHERE has_column_privilege(
                                       current_user, c.oid, fixed.column_name, 'UPDATE'
                                   )
                               )
                             )
                       )
                FROM pg_roles WHERE rolname = current_user
                """
            )
            flags = cursor.fetchone()
            if flags is None or any(flags):
                raise CommandError(
                    "Unsafe runtime database role. Run dbsetup, then use orderdesk_app."
                )
            for table, mutable, immutable in (
                (
                    "orders_draftorder",
                    (
                        "customer_name",
                        "customer_reference",
                        "original_intake_text",
                        "updated_at",
                    ),
                    (
                        "id",
                        "organization_id",
                        "initiating_user_id",
                        "status",
                        "source_type",
                        "created_at",
                    ),
                ),
                (
                    "orders_draftorderline",
                    (
                        "position",
                        "requested_sku",
                        "requested_description",
                        "quantity",
                        "unit",
                        "catalogue_item_id",
                        "catalogue_sku_snapshot",
                        "catalogue_description_snapshot",
                        "updated_at",
                    ),
                    ("id", "organization_id", "order_id", "created_at"),
                ),
            ):
                cursor.execute(
                    "SELECT c.relowner = (SELECT oid FROM pg_roles WHERE rolname = "
                    "'orderdesk_migrator'), c.relrowsecurity, c.relforcerowsecurity, "
                    "has_table_privilege(current_user, c.oid, 'SELECT'), "
                    "has_table_privilege(current_user, c.oid, 'INSERT'), "
                    "has_table_privilege(current_user, c.oid, 'UPDATE'), "
                    "has_table_privilege(current_user, c.oid, "
                    "'DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN') "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relname = %s AND c.relkind = 'r'",
                    [table],
                )
                state = cursor.fetchone()
                if state != (True, True, True, True, True, False, False):
                    raise CommandError(f"Unsafe runtime grants or RLS for {table}.")
                for column in mutable:
                    cursor.execute(
                        "SELECT has_column_privilege(current_user, %s, %s, 'UPDATE')",
                        [f"public.{table}", column],
                    )
                    if cursor.fetchone()[0] is not True:
                        raise CommandError(
                            f"Missing draft update grant: {table}.{column}."
                        )
                for column in immutable:
                    cursor.execute(
                        "SELECT has_column_privilege(current_user, %s, %s, 'UPDATE')",
                        [f"public.{table}", column],
                    )
                    if cursor.fetchone()[0]:
                        raise CommandError(
                            f"Immutable draft column writable: {table}.{column}."
                        )
        self.stdout.write(self.style.SUCCESS("Runtime database role is restricted."))
