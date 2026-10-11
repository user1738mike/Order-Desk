"""Non-destructive direct runtime RLS proof on restored acceptance data."""

import json
import os
import sys
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local_production")
sys.path.insert(0, "/app")
django.setup()

from django.db import connection, transaction  # noqa: E402


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


fixture = json.loads(Path("/run-state/fixture.json").read_text(encoding="ascii"))
with connection.cursor() as cursor:
    cursor.execute(
        "SELECT current_database(), current_user, session_user, rolsuper, "
        "rolbypassrls FROM pg_roles WHERE rolname=current_user"
    )
    require(
        cursor.fetchone()
        == ("test_orderdesk", "orderdesk_app", "orderdesk_app", False, False),
        "Unexpected restored runtime identity.",
    )
    cursor.execute(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
        "ON n.oid=c.relnamespace WHERE n.nspname='public' "
        "AND c.relname LIKE 'orders_%' AND c.relkind='r' "
        "AND (NOT c.relrowsecurity OR NOT c.relforcerowsecurity "
        "OR pg_get_userbyid(c.relowner) <> 'orderdesk_migrator')"
    )
    require(cursor.fetchone()[0] == 0, "Restored order RLS/ownership missing.")
    cursor.execute("SELECT count(*) FROM orders_purchaseorder")
    require(cursor.fetchone()[0] == 0, "Unscoped restored rows exposed.")

for workspace, foreign in ((fixture["a"], fixture["b"]), (fixture["b"], fixture["a"])):
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('orderdesk.organization_id', %s, true), "
            "set_config('orderdesk.user_id', %s, true)",
            [workspace, fixture["user"]],
        )
        # Deliberately no application tenant filters.
        cursor.execute(
            "SELECT DISTINCT organization_id::text FROM orders_purchaseorder"
        )
        require(
            cursor.fetchall() == [(workspace,)], "Restored cross-tenant orders exposed."
        )
        cursor.execute(
            "SELECT count(*) FROM orders_purchaseorder WHERE organization_id=%s",
            [foreign],
        )
        require(cursor.fetchone()[0] == 0, "Foreign restored rows exposed.")
        cursor.execute("SELECT DISTINCT organization_id::text FROM catalog_catalogitem")
        require(
            cursor.fetchall() == [(workspace,)],
            "Restored catalogue tenant boundary failed.",
        )
print(
    "PASS: restored two-tenant direct restricted-role RLS, "
    "unscoped denial and migrator ownership."
)
