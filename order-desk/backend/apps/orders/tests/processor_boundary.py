"""Direct application-role processor rights, denials and waiting demotion."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection, connections, transaction
from django.test import override_settings
from django.utils import timezone

from apps.catalog.services import create_catalog_item
from apps.catalog.tests.runtime_rls import OWNER_ALIAS
from apps.customers.services import save_reference
from apps.orders import incoming
from apps.orders.extraction_services import process_extraction
from apps.orders.models import DraftOrder, PurchaseOrder
from apps.orders.services import create_draft_order
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.transactions import tenant_scope


def membership(checks, role):
    with transaction.atomic(using=OWNER_ALIAS):
        Organization.objects.using(OWNER_ALIAS).select_for_update().get(pk=checks.a.pk)
        Membership.objects.using(OWNER_ALIAS).filter(
            pk=checks.admin_membership.pk
        ).update(role=role)


def preparation_scope(checks):
    account = save_reference(
        actor=checks.admin,
        organization_id=checks.a.pk,
        kind="account",
        data=lambda: {
            "code": "PROCESSOR-00042",
            "display_name": "Synthetic processor customer",
        },
    )
    item = create_catalog_item(
        actor=checks.admin,
        organization_id=checks.a.pk,
        data={"sku": "PROCESSOR-00042", "description": "Synthetic processor product"},
        materialize=lambda row: row.pk,
    )
    membership(checks, MembershipRole.PROCESSOR)
    client, token = checks._credential_client(checks.admin)
    base = f"/api/v1/workspaces/{checks.a.pk}/"

    def post(suffix, body, revision=None):
        return client.post(
            base + suffix,
            body,
            format="json",
            HTTP_X_CSRFTOKEN=token,
            **({"HTTP_IF_MATCH": '"' + revision + '"'} if revision else {}),
        )

    with (
        TemporaryDirectory() as private,
        override_settings(PRIVATE_DOCUMENT_ROOT=private),
    ):
        source, _ = incoming.receive(
            actor=checks.admin,
            organization_id=checks.a.pk,
            operation_key=uuid4(),
            upload=lambda: SimpleUploadedFile(
                "processor.csv", b"sku,quantity,unit\nPROCESSOR-00042,1.250,case\n"
            ),
        )
        linked = post(
            f"incoming/{source['id']}/link/",
            {
                "operation_key": str(uuid4()),
                "customer_name": "Original requested customer",
                "customer_reference": "00009",
            },
        )
        checks.assertEqual(linked.status_code, 201, linked.content)
        draft = str(linked.json()["draft"])
        extraction = source["extraction_url"]
        queued = client.post(extraction, {}, format="json", HTTP_X_CSRFTOKEN=token)
        checks.assertEqual(queued.status_code, 202, queued.content)
        checks.assertEqual(
            process_extraction(
                actor=checks.admin,
                organization_id=checks.a.pk,
                job_id=UUID(queued.json()["id"]),
            ),
            "succeeded",
        )
        review = client.get(extraction + "review/", {"draft_id": draft})
        checks.assertEqual(review.status_code, 200, review.content)
        value = review.json()
        payload = {
            "operation_key": str(uuid4()),
            "job_id": queued.json()["id"],
            "draft_id": draft,
            "result_revision": value["result_revision"],
            "expected_draft_revision": value["draft_revision"],
            "mappings": [
                {
                    "candidate_id": value["results"][0]["candidate_id"],
                    "action": "create",
                    "position": 1,
                    "fields": ["sku", "quantity", "unit"],
                    "corrections": {},
                }
            ],
        }
        for expected in (201, 200):
            applied = client.post(
                extraction + "apply/", payload, format="json", HTTP_X_CSRFTOKEN=token
            )
            checks.assertEqual(applied.status_code, expected, applied.content)
        path = f"draft-orders/{draft}/"
        lines = client.get(base + path + "lines/").json()
        checks.assertEqual(lines["count"], 1)
        revision = client.get(base + path + "revision/").json()["revision"]
        attached = post(
            path + f"lines/{lines['results'][0]['id']}/attach/",
            {"catalogue_item_id": str(item)},
            revision,
        )
        checks.assertEqual(attached.status_code, 200, attached.content)
        confirmation = f"customers/drafts/{draft}/confirmation/"
        preview = client.get(base + confirmation, {"customer_id": account["id"]})
        checks.assertEqual(preview.status_code, 200, preview.content)
        value = preview.json()
        confirm_payload = {
            "operation_key": str(uuid4()),
            "customer_id": account["id"],
            "reference_revision": value["candidate"]["reference_revision"],
            "expected_draft_revision": value["draft_revision"],
        }
        checks.assertEqual(post(confirmation, confirm_payload).status_code, 201)
        checks.assertTrue(
            client.get(base + path + "readiness/").json()["ready_to_convert"]
        )
        checks.assertEqual(post(path + "convert/", {}).status_code, 403)
        for action in ("approve/", "reject/", "submit/", "exports/"):
            checks.assertEqual(
                post(
                    f"orders/{checks.rows[checks.a.pk][PurchaseOrder].pk}/" + action, {}
                ).status_code,
                403,
            )
        checks.assertEqual(
            post(
                "customers/", {"code": "DENIED", "display_name": "Denied"}
            ).status_code,
            403,
        )
        checks.assertEqual(post("catalog/items/", {"sku": "DENIED"}).status_code, 403)
        with tenant_scope(user=checks.admin, workspace_id=checks.a.pk, write=True):
            checks.assertEqual(
                PurchaseOrder.objects.filter(organization_id=checks.a.pk).update(
                    status="approved",
                    reviewed_by_id=checks.admin.pk,
                    reviewed_at=timezone.now(),
                ),
                0,
            )
        checks._expect_error(
            "42501",
            checks._write_scope(),
            lambda: PurchaseOrder.objects.create(
                organization_id=checks.a.pk,
                created_by_id=checks.admin.pk,
                customer_name="Denied",
                purchase_order_number="PROCESSOR-DENIED",
            ),
        )
        foreign_url = source["download_url"].replace(str(checks.a.pk), str(checks.b.pk))
        checks.assertEqual(client.get(foreign_url).status_code, 404)
        membership(checks, MembershipRole.VIEWER)
        checks.assertEqual(
            client.post(
                extraction + "apply/", payload, format="json", HTTP_X_CSRFTOKEN=token
            ).status_code,
            403,
        )
        checks.assertEqual(post(confirmation, confirm_payload).status_code, 403)
        checks.assertEqual(
            post("draft-orders/", {"customer_name": "Denied"}).status_code, 403
        )


def waiting_demotion(checks):
    membership(checks, MembershipRole.PROCESSOR)
    ready = Queue()

    def attempt():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                ready.put(cursor.fetchone()[0])
            with checks.assertRaises(PermissionDenied):
                create_draft_order(
                    actor=checks.admin,
                    organization_id=checks.a.pk,
                    customer_name="PROCESSOR-DEMOTION-DENIED",
                )
        finally:
            connections.close_all()

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
            ).update(role=MembershipRole.VIEWER)
            result = pool.submit(attempt)
            pid = ready.get(timeout=10)
            checks.assertNotEqual(pid, blocker)
            deadline = monotonic() + 5
            pause = Event()
            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_blocking_pids(%s)", [pid])
                    if blocker in cursor.fetchone()[0]:
                        break
                pause.wait(0.02)
            else:
                checks.fail("Processor did not wait on membership transaction.")
        result.result(timeout=12)
    checks.assertFalse(
        DraftOrder.objects.using(OWNER_ALIAS)
        .filter(organization_id=checks.a.pk, customer_name="PROCESSOR-DEMOTION-DENIED")
        .exists()
    )
