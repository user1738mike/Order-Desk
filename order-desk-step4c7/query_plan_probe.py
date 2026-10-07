"""Disposable search-plan measurement; run only through the rlscheck service.

Untracked verification artifact. Never run against a main database, override
planner settings, or use its maintenance alias for measured catalogue reads.
"""

import json
import os
from time import perf_counter

import django


def compact_plan(raw: str) -> dict:
    document = json.loads(raw)[0]
    nodes = []

    def visit(node: dict) -> None:
        keys = (
            "Node Type",
            "Relation Name",
            "Index Name",
            "Plan Rows",
            "Actual Rows",
            "Actual Loops",
            "Rows Removed by Filter",
            "Rows Removed by Index Recheck",
            "Shared Hit Blocks",
            "Shared Read Blocks",
        )
        nodes.append({key: node[key] for key in keys if key in node})
        for child in node.get("Plans", []):
            visit(child)

    visit(document["Plan"])
    return {
        "planning_ms": document.get("Planning Time"),
        "execution_ms": document.get("Execution Time"),
        "nodes": nodes,
    }


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    django.setup()

    from django.db import connection, connections, transaction
    from django.test.utils import CaptureQueriesContext

    from apps.accounts.models import User
    from apps.catalog.management.commands.verify_catalog_rls import Command
    from apps.catalog.models import CatalogItem
    from apps.catalog.selectors import (
        catalog_item_by_sku,
        catalog_items_for_workspace,
    )
    from apps.catalog.serializers import CatalogItemSerializer
    from apps.catalog.tests.runtime_rls import OWNER_ALIAS, RuntimeCatalogRLSChecks
    from apps.organizations.models import Membership, Organization
    from apps.organizations.transactions import tenant_scope

    verifier = Command()
    verifier._owner_registered = False
    fixture = None
    report = None
    try:
        # Reuse the committed database-name, direct-identity, FORCE RLS, policy,
        # grant, and restricted-owner checks before creating a single fixture.
        verifier._validate_local_target()
        verifier._audit_runtime_boundary()
        verifier._register_fixture_owner()
        fixture = RuntimeCatalogRLSChecks(
            methodName="test_missing_both_context_ids_exposes_no_rows"
        )
        fixture.setUp()
        per_tenant = 1000
        with transaction.atomic(using=OWNER_ALIAS):
            with connections[OWNER_ALIAS].cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SET LOCAL statement_timeout = '15s'")
            for workspace in (fixture.a, fixture.b):
                CatalogItem.objects.using(OWNER_ALIAS).bulk_create(
                    [
                        CatalogItem(
                            organization_id=workspace.pk,
                            sku=f"PLAN-{index:05d}",
                            description=(
                                "Synthetic plan needle"
                                if index % 10 == 0
                                else "Synthetic plan ordinary"
                            ),
                            is_active=index % 3 != 0,
                        )
                        for index in range(per_tenant)
                    ],
                    batch_size=250,
                )
            # The maintenance alias owns this test table. No planner switches
            # or grants change; ANALYZE simply reflects the synthetic rows.
            with connections[OWNER_ALIAS].cursor() as cursor:
                cursor.execute("ANALYZE public.catalog_catalogitem")

        with tenant_scope(user=fixture.admin, workspace_id=fixture.a.pk):
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '15s'")
                cursor.execute(
                    "SELECT current_database(), current_user, session_user, "
                    "current_setting('transaction_read_only')"
                )
                identity = cursor.fetchone()
            fixture.assertEqual(
                identity, ("test_orderdesk", "orderdesk_app", "orderdesk_app", "on")
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_encoding_to_char(d.encoding), d.datcollate, "
                    "d.datctype, to_jsonb(d)->>'datlocprovider', "
                    "to_jsonb(d)->>'datlocale', current_setting('server_version') "
                    "FROM pg_catalog.pg_database d "
                    "WHERE d.datname = current_database()"
                )
                collation = cursor.fetchone()
                cursor.execute(
                    "SELECT c.collname, c.collprovider, c.collisdeterministic "
                    "FROM pg_catalog.pg_attribute a "
                    "JOIN pg_catalog.pg_collation c ON c.oid = a.attcollation "
                    "WHERE a.attrelid = 'public.catalog_catalogitem'::regclass "
                    "AND a.attname = 'sku'"
                )
                sku_collation = cursor.fetchone()
                cursor.execute(
                    "SELECT indexname, indexdef FROM pg_catalog.pg_indexes "
                    "WHERE schemaname = 'public' AND tablename = 'catalog_catalogitem' "
                    "ORDER BY indexname"
                )
                indexes = cursor.fetchall()

            items = catalog_items_for_workspace(
                organization_id=fixture.a.pk, q="needle", is_active=True
            )
            started = perf_counter()
            with CaptureQueriesContext(connection) as fetch_queries:
                count = items.count()
                rows = list(items[:50])
            fetch_ms = (perf_counter() - started) * 1000
            expected_count = sum(
                index % 10 == 0 and index % 3 != 0 for index in range(per_tenant)
            )
            fixture.assertEqual(count, expected_count)
            fixture.assertEqual(len(rows), 50)
            fixture.assertEqual(len(fetch_queries), 2)
            with CaptureQueriesContext(connection) as serialization_queries:
                data = CatalogItemSerializer(rows, many=True).data
            fixture.assertEqual(len(serialization_queries), 0)
            fixture.assertTrue(
                all(
                    row["organization_id"] == str(fixture.a.pk)
                    and row["is_active"] is True
                    for row in data
                )
            )
            search_plan = compact_plan(
                items[:50].explain(analyze=True, buffers=True, format="json")
            )

            exact = catalog_item_by_sku(
                organization_id=fixture.a.pk, sku="PLAN-00042"
            )
            with CaptureQueriesContext(connection) as exact_fetch_queries:
                item = exact.first()
            fixture.assertIsNotNone(item)
            fixture.assertEqual(item.organization_id, fixture.a.pk)
            fixture.assertFalse(item.is_active)
            fixture.assertEqual(len(exact_fetch_queries), 1)
            with CaptureQueriesContext(connection) as exact_serialization_queries:
                exact_data = CatalogItemSerializer(item).data
            fixture.assertEqual(len(exact_serialization_queries), 0)
            fixture.assertEqual(exact_data["organization_id"], str(fixture.a.pk))
            exact_plan = compact_plan(
                exact.order_by("pk")[:1].explain(
                    analyze=True, buffers=True, format="json"
                )
            )
            report = {
                "scope_identity": identity,
                "synthetic_added_per_tenant": per_tenant,
                "synthetic_tenants": 2,
                "database_collation": {
                    "encoding": collation[0],
                    "collate": collation[1],
                    "ctype": collation[2],
                    "provider": collation[3],
                    "locale": collation[4],
                    "postgresql": collation[5],
                },
                "sku_collation": sku_collation,
                "indexes": indexes,
                "filtered_count": count,
                "page_rows": len(rows),
                "count_plus_page_database_queries": len(fetch_queries),
                "count_plus_page_wall_ms": round(fetch_ms, 3),
                "page_serialization_extra_queries": len(serialization_queries),
                "exact_fetch_queries": len(exact_fetch_queries),
                "exact_serialization_extra_queries": len(exact_serialization_queries),
                "search_page_plan": search_plan,
                "exact_sku_plan": exact_plan,
            }
        fixture._assert_clean()
    finally:
        try:
            if fixture is not None:
                if not fixture.doCleanups():
                    raise RuntimeError("Synthetic fixture cleanup failed.")
                # Assert cleanup of these exact tracked IDs, not global emptiness.
                for model, filters in (
                    (CatalogItem, {"organization_id__in": fixture.workspace_ids}),
                    (Membership, {"organization_id__in": fixture.workspace_ids}),
                    (Organization, {"pk__in": fixture.workspace_ids}),
                    (User, {"pk__in": fixture.user_ids}),
                ):
                    if model.objects.using(OWNER_ALIAS).filter(**filters).exists():
                        raise RuntimeError("A synthetic fixture remains after cleanup.")
                with connections[OWNER_ALIAS].cursor() as cursor:
                    cursor.execute("ANALYZE public.catalog_catalogitem")
                if report is not None:
                    report["tracked_fixture_cleanup_verified"] = True
        finally:
            connection.close()
            if verifier._owner_registered:
                connections[OWNER_ALIAS].close()
                del connections[OWNER_ALIAS]
                connections.databases.pop(OWNER_ALIAS)
    if report is None:
        raise RuntimeError("No measurement was produced.")
    print(json.dumps(report, separators=(",", ":"), ensure_ascii=True))


if __name__ == "__main__":
    main()
