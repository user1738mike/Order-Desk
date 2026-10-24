"""Guarded orderdesk_app verification with independent owner fixtures."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from time import monotonic
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, connections, transaction
from django.test import override_settings

from apps.catalog.tests.runtime_rls import OWNER_ALIAS
from apps.customers.models import (
    CustomerAccount,
    CustomerAlias,
    CustomerLocation,
    DraftCustomerDecision,
    OrderCustomerSnapshot,
    ReferenceWriteReceipt,
)
from apps.customers.services import ReferenceConflict, save_reference
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.transactions import tenant_scope

TABLES = {
    "customers_customeraccount": ("customer", "admin"),
    "customers_customerlocation": ("customer_site", "admin"),
    "customers_customeralias": ("customer_alias", "admin"),
    "customers_draftcustomerdecision": ("customer_decision", "reviewer"),
    "customers_ordercustomersnapshot": ("customer_snapshot", "admin"),
    "customers_referencewritereceipt": ("customer_write", "admin"),
}


def audit(cursor):
    for table, (prefix, writers) in TABLES.items():
        cursor.execute(
            "SELECT pg_get_userbyid(c.relowner),c.relrowsecurity,c.relforcerowsecurity "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relname=%s AND c.relkind='r'",
            [table],
        )
        if cursor.fetchone() != ("orderdesk_migrator", True, True):
            raise CommandError("Customer table ownership/forced RLS is invalid.")
        for privilege in (
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "TRUNCATE",
            "TRIGGER",
            "REFERENCES",
            "MAINTAIN",
        ):
            cursor.execute(
                "SELECT has_table_privilege(current_user,%s,%s)", [table, privilege]
            )
            expected = privilege in {"SELECT", "INSERT", "UPDATE"} and not (
                table
                in {
                    "customers_ordercustomersnapshot",
                    "customers_referencewritereceipt",
                }
                and privilege == "UPDATE"
            )
            if cursor.fetchone()[0] is not expected:
                raise CommandError("Unexpected customer table runtime grants.")
        cursor.execute(
            "SELECT policyname,permissive,roles,cmd,qual,with_check FROM pg_policies "
            "WHERE schemaname='public' AND tablename=%s",
            [table],
        )
        policies = {
            name: (permissive, roles, cmd, qual, check)
            for name, permissive, roles, cmd, qual, check in cursor.fetchall()
        }
        if set(policies) != {
            prefix + suffix
            for suffix in (
                "_tenant_boundary",
                "_member_read",
                "_reviewer_insert",
                "_reviewer_update",
                "_owner_maintenance",
            )
        }:
            raise CommandError("Unexpected customer policy set.")
        tenant = policies[prefix + "_tenant_boundary"]
        if (
            tenant[:3] != ("RESTRICTIVE", ["orderdesk_app"], "ALL")
            or tenant[3] != tenant[4]
        ):
            raise CommandError("Customer tenant policy is not restrictive/symmetric.")
        if any(
            value not in tenant[3]
            for value in (
                "orderdesk.organization_id",
                "orderdesk.user_id",
                "m.is_active",
                "o.is_active",
                "u.is_active",
            )
        ):
            raise CommandError("Customer tenant membership policy is incomplete.")
        for suffix, command in (
            ("_reviewer_insert", "INSERT"),
            ("_reviewer_update", "UPDATE"),
        ):
            policy = policies[prefix + suffix]
            expression = policy[4] if command == "INSERT" else policy[3]
            if (
                policy[:3] != ("PERMISSIVE", ["orderdesk_app"], command)
                or not expression
            ):
                raise CommandError("Customer writer policy is invalid.")
            if "'admin'" not in expression or (
                ("'reviewer'" in expression) != (writers == "reviewer")
            ):
                raise CommandError("Customer writer role matrix is invalid.")


def account(checks, code, workspace=None):
    return save_reference(
        actor=checks.admin,
        organization_id=(workspace or checks.a).pk,
        kind="account",
        data=lambda: {
            "code": code,
            "display_name": "Synthetic confirmed " + code,
            "destination_id": "DEST-" + code,
        },
    )


def reference_scope(checks):
    a, b = account(checks, "00042"), account(checks, "00043", checks.b)
    checks.assertEqual(CustomerAccount.objects.count(), 0)
    checks.assertEqual(ReferenceWriteReceipt.objects.count(), 0)
    with tenant_scope(user=checks.admin, workspace_id=checks.a.pk):
        checks.assertEqual(
            list(CustomerAccount.objects.values_list("id", flat=True)), [UUID(a["id"])]
        )
        checks.assertFalse(CustomerAccount.objects.filter(pk=b["id"]).exists())
    with tenant_scope(user=checks.viewer, workspace_id=checks.a.pk, write=True):
        checks.assertEqual(
            CustomerAccount.objects.filter(pk=a["id"]).update(display_name="Denied"), 0
        )
    checks._expect_error(
        "42501",
        checks._write_scope(checks.reviewer),
        lambda: CustomerAccount.objects.create(
            organization_id=checks.a.pk,
            created_by_id=checks.reviewer.pk,
            updated_by_id=checks.reviewer.pk,
            code="DENIED",
            display_name="Denied",
        ),
    )
    replay = save_reference(
        actor=checks.admin,
        organization_id=checks.a.pk,
        kind="account",
        operation_key=UUID(a["operation_key"]),
        data=lambda: {
            "code": "00042",
            "display_name": "Synthetic confirmed 00042",
            "destination_id": "DEST-00042",
        },
    )
    checks.assertTrue(replay["replayed"])
    checks.assertEqual(replay["id"], a["id"])
    checks._expect_error(
        "42501",
        checks._write_scope(),
        lambda: ReferenceWriteReceipt.objects.filter(
            operation_key=a["operation_key"]
        ).update(response={}),
    )
    checks._expect_error(
        "23503",
        checks._write_scope(),
        lambda: CustomerLocation.objects.create(
            organization_id=checks.a.pk,
            customer_id=b["id"],
            created_by_id=checks.admin.pk,
            updated_by_id=checks.admin.pk,
            code="CROSS",
            display_name="Denied",
        ),
    )
    checks._expect_error(
        "23514",
        checks._write_scope(),
        lambda: CustomerAccount.objects.filter(pk=a["id"]).update(code="CHANGED"),
    )
    client, token = checks._credential_client(checks.reviewer)
    path = f"/api/v1/workspaces/{checks.a.pk}/customers/"
    checks.assertEqual(client.get(path).status_code, 200)
    checks.assertEqual(
        client.post(
            path,
            {"code": "HTTP-DENIED", "display_name": "Denied"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        ).status_code,
        403,
    )


def alias_race(checks):
    records = [account(checks, "A"), account(checks, "B")]
    ready = Barrier(2)
    identities = []

    def attempt(record):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout='5s'")
                cursor.execute("SET statement_timeout='10s'")
                cursor.execute("SELECT current_user,session_user,pg_backend_pid()")
                identities.append(cursor.fetchone())
            ready.wait(timeout=10)
            try:
                save_reference(
                    actor=checks.admin,
                    organization_id=checks.a.pk,
                    kind="alias",
                    customer_id=UUID(record["id"]),
                    data=lambda: {
                        "value": "SAME-APPROVED-ALIAS",
                        "provenance": "Explicit synthetic approval",
                    },
                )
                return "created"
            except ReferenceConflict:
                return "conflict"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, records))
    checks.assertCountEqual(outcomes, ["created", "conflict"])
    checks.assertEqual(len({row[2] for row in identities}), 2)
    checks.assertTrue(
        all(row[:2] == ("orderdesk_app", "orderdesk_app") for row in identities)
    )
    with tenant_scope(user=checks.admin, workspace_id=checks.a.pk):
        checks.assertEqual(CustomerAlias.objects.filter(is_active=True).count(), 1)


def import_scope(checks):
    raw = (
        b"code,display_name,destination_id,requires_location,is_active\n"
        b"00009,Synthetic imported,000007,false,true\n"
    )
    client, token = checks._credential_client(checks.admin)
    base = f"/api/v1/workspaces/{checks.a.pk}/customers/"
    key = str(uuid4())

    def upload(mode):
        return client.post(
            base + f"imports/{mode}/",
            {"file": SimpleUploadedFile("customers.csv", raw)},
            format="multipart",
            HTTP_X_CSRFTOKEN=token,
            HTTP_IDEMPOTENCY_KEY=key,
        )

    checked = upload("validate")
    checks.assertEqual(checked.status_code, 200, checked.content)
    checks.assertEqual(upload("create").status_code, 201)
    replay = upload("create")
    checks.assertEqual(replay.status_code, 200, replay.content)
    checks.assertEqual(replay.json()["original_created"], 1)
    with tenant_scope(user=checks.admin, workspace_id=checks.a.pk):
        customer = CustomerAccount.objects.get(code="00009")
        checks.assertEqual(customer.destination_id, "000007")
        checks.assertEqual(
            ReferenceWriteReceipt.objects.get(operation_key=key).actor_id,
            checks.admin.pk,
        )
    reviewer, _ = checks._credential_client(checks.reviewer)
    checks.assertEqual(reviewer.get(base + f"operations/{key}/").status_code, 403)
    checks.assertEqual(
        client.get(
            base.replace(str(checks.a.pk), str(checks.b.pk)) + f"operations/{key}/"
        ).status_code,
        404,
    )


def waiting_admin_demotion(checks):
    ready = Queue()

    def attempt():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout='8s'")
                cursor.execute("SELECT current_user,session_user,pg_backend_pid()")
                identity = cursor.fetchone()
            checks.assertEqual(identity[:2], ("orderdesk_app", "orderdesk_app"))
            ready.put(identity[2])
            with checks.assertRaises(PermissionDenied):
                account(checks, "DEMOTION-DENIED")
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic(using=OWNER_ALIAS):
            Organization.objects.using(OWNER_ALIAS).select_for_update().get(
                pk=checks.a.pk
            )
            with connections[OWNER_ALIAS].cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                blocker = cursor.fetchone()[0]
            Membership.objects.using(OWNER_ALIAS).filter(
                pk=checks.admin_membership.pk
            ).update(role=MembershipRole.REVIEWER)
            result = pool.submit(attempt)
            pid = ready.get(timeout=10)
            deadline = monotonic() + 5
            pause = Event()
            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_blocking_pids(%s)", [pid])
                    if blocker in cursor.fetchone()[0]:
                        break
                pause.wait(0.02)
            else:
                checks.fail(
                    "Customer reference writer did not wait on membership transaction."
                )
        result.result(timeout=12)
    checks.assertFalse(
        CustomerAccount.objects.using(OWNER_ALIAS)
        .filter(organization=checks.a, code="DEMOTION-DENIED")
        .exists()
    )


def confirmation_scope(checks):
    from apps.catalog.models import CatalogItem
    from apps.orders import incoming
    from apps.orders.models import DraftOrderLine

    with (
        TemporaryDirectory() as private,
        override_settings(PRIVATE_DOCUMENT_ROOT=private),
    ):
        customer = account(checks, "CONFIRM")
        source, _ = incoming.receive(
            actor=checks.admin,
            organization_id=checks.a.pk,
            operation_key=uuid4(),
            upload=lambda: SimpleUploadedFile(
                "confirmed.csv", b"sku,quantity\n00042,1.250\n"
            ),
        )
        linked, _ = incoming.link(
            actor=checks.admin,
            organization_id=checks.a.pk,
            document_id=UUID(source["id"]),
            data=lambda: {
                "operation_key": str(uuid4()),
                "customer_name": "Original source buyer",
            },
        )
        draft_id = str(linked["draft"])
        base = f"/api/v1/workspaces/{checks.a.pk}/customers/"
        url = base + f"drafts/{draft_id}/confirmation/"
        reviewer, token = checks._credential_client(checks.reviewer)
        preview = reviewer.get(url, {"customer_id": customer["id"]})
        checks.assertEqual(preview.status_code, 200, preview.content)
        payload = {
            "operation_key": str(uuid4()),
            "customer_id": customer["id"],
            "reference_revision": preview.json()["candidate"]["reference_revision"],
            "expected_draft_revision": preview.json()["draft_revision"],
        }
        response = reviewer.post(url, payload, format="json", HTTP_X_CSRFTOKEN=token)
        checks.assertEqual(response.status_code, 201, response.content)
        decision = response.json()
        checks.assertEqual(decision["actor_id"], str(checks.reviewer.pk))
        checks._expect_error(
            "23514",
            checks._write_scope(checks.reviewer),
            lambda: DraftCustomerDecision.objects.filter(pk=decision["id"]).update(
                snapshot={}
            ),
        )
        item = CatalogItem.objects.using(OWNER_ALIAS).create(
            organization_id=checks.a.pk,
            sku="00042",
            description="Synthetic confirmed item",
        )
        DraftOrderLine.objects.using(OWNER_ALIAS).create(
            organization_id=checks.a.pk,
            order_id=draft_id,
            position=1,
            requested_sku=item.sku,
            quantity="1.250",
            unit="case",
            catalogue_item_id=item.pk,
            catalogue_sku_snapshot=item.sku,
            catalogue_description_snapshot=item.description,
        )
        admin, admin_token = checks._credential_client(checks.admin)
        converted = admin.post(
            f"/api/v1/workspaces/{checks.a.pk}/draft-orders/{draft_id}/convert/",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=admin_token,
        )
        checks.assertEqual(converted.status_code, 201, converted.content)
        order_id = converted.json()["id"]
        snapshot_url = base + f"orders/{order_id}/snapshot/"
        viewer, viewer_token = checks._credential_client(checks.viewer)
        snapshot = viewer.get(snapshot_url)
        checks.assertEqual(snapshot.status_code, 200, snapshot.content)
        frozen = snapshot.json()["snapshot"]
        checks.assertEqual(frozen["payload"]["account"]["code"], "CONFIRM")
        checks.assertEqual(frozen["decision_id"], decision["id"])
        checks.assertEqual(
            viewer.post(
                url, payload, format="json", HTTP_X_CSRFTOKEN=viewer_token
            ).status_code,
            403,
        )
        checks.assertEqual(OrderCustomerSnapshot.objects.count(), 0)
        with tenant_scope(user=checks.admin, workspace_id=checks.b.pk):
            checks.assertFalse(
                OrderCustomerSnapshot.objects.filter(order_id=order_id).exists()
            )
            checks.assertFalse(
                DraftCustomerDecision.objects.filter(pk=decision["id"]).exists()
            )
        checks._expect_error(
            "42501",
            checks._write_scope(),
            lambda: OrderCustomerSnapshot.objects.filter(order_id=order_id).update(
                payload={}
            ),
        )
        replay = reviewer.post(url, payload, format="json", HTTP_X_CSRFTOKEN=token)
        checks.assertEqual(replay.status_code, 200, replay.content)
        Membership.objects.using(OWNER_ALIAS).filter(
            user=checks.reviewer, organization=checks.a
        ).update(is_active=False)
        checks.assertEqual(
            reviewer.post(
                url, payload, format="json", HTTP_X_CSRFTOKEN=token
            ).status_code,
            403,
        )


def cleanup(checks):
    for model in (ReferenceWriteReceipt, OrderCustomerSnapshot, DraftCustomerDecision):
        model.objects.using(OWNER_ALIAS).filter(
            organization_id__in=checks.workspace_ids
        ).delete()


def cleanup_references(checks):
    for model in (CustomerAlias, CustomerLocation, CustomerAccount):
        model.objects.using(OWNER_ALIAS).filter(
            organization_id__in=checks.workspace_ids
        ).delete()
