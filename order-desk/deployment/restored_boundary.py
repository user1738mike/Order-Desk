"""Non-destructive direct runtime RLS proof on restored acceptance data."""

import json
import os
import sys
from pathlib import Path

import django
from psycopg import sql

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
    cursor.execute("SELECT count(*) FROM orders_orderdocument")
    require(cursor.fetchone()[0] == 0, "Unscoped restored sources exposed.")
    state = json.loads(Path("/run-state/workflow.json").read_text(encoding="utf-8"))
    if state.get("customer"):
        from apps.customers.tests.runtime_boundary import audit

        audit(cursor)
        for table in (
            "customers_customeraccount",
            "customers_customerlocation",
            "customers_customeralias",
            "customers_draftcustomerdecision",
            "customers_ordercustomersnapshot",
            "customers_referencewritereceipt",
        ):
            cursor.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
            )
            require(
                cursor.fetchone()[0] == 0, "Unscoped restored customer data exposed."
            )

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
        state = json.loads(Path("/run-state/workflow.json").read_text(encoding="utf-8"))
        if incoming := state.get("incoming"):
            cursor.execute(
                "SELECT draft_id::text FROM orders_orderdocument "
                "WHERE id=%s AND order_id IS NULL",
                [incoming["document"]["id"]],
            )
            expected = (
                [(incoming["draft_id"],)] if workspace == incoming["workspace"] else []
            )
            require(
                cursor.fetchall() == expected,
                "Restored incoming link tenant boundary failed.",
            )
        if customer := state.get("customer"):
            for table, key in (
                ("customers_customeraccount", "account_id"),
                ("customers_customerlocation", "site_id"),
                ("customers_customeralias", "alias_id"),
                ("customers_draftcustomerdecision", "decision_id"),
                ("customers_ordercustomersnapshot", "snapshot_id"),
            ):
                cursor.execute(
                    sql.SQL("SELECT id::text FROM {} WHERE id=%s").format(
                        sql.Identifier(table)
                    ),
                    [customer[key]],
                )
                require(
                    cursor.fetchall()
                    == (
                        [(customer[key],)] if workspace == customer["workspace"] else []
                    ),
                    "Restored customer record tenant boundary failed.",
                )
            cursor.execute(
                "SELECT organization_id::text FROM customers_referencewritereceipt "
                "WHERE operation_key=%s",
                [customer["receipt_key"]],
            )
            require(
                cursor.fetchall()
                == ([(workspace,)] if workspace == customer["workspace"] else []),
                "Restored customer receipt tenant boundary failed.",
            )
print(
    "PASS: restored two-tenant direct restricted-role RLS, "
    "unscoped denial and migrator ownership."
)
