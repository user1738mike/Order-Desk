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
                       )
                FROM pg_roles WHERE rolname = current_user
                """
            )
            flags = cursor.fetchone()
        if flags is None or any(flags):
            raise CommandError(
                "Unsafe runtime database role. Run dbsetup, then use orderdesk_app."
            )
        self.stdout.write(self.style.SUCCESS("Runtime database role is restricted."))
