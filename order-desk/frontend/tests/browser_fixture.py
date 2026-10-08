"""Synthetic browser fixtures, guarded to the dedicated maintenance connection.

Run only through the browser smoke harness. Credentials stay in ignored var/.
"""

import json
import os
import unittest
from pathlib import Path
from uuid import uuid4

from django.contrib.sessions.models import Session
from django.db import connection, transaction

from apps.accounts.login_limits import login_bucket_key
from apps.accounts.models import LoginAttemptBucket, User
from apps.catalog.models import CatalogItem
from apps.orders.models import (
    DraftOrder,
    DraftOrderLine,
    PurchaseOrder,
    PurchaseOrderLine,
)
from apps.organizations.models import Membership, MembershipRole, Organization

with connection.cursor() as cursor:
    cursor.execute("SELECT current_database(), current_user, session_user")
    if cursor.fetchone() != (
        "test_orderdesk",
        "orderdesk_migrator",
        "orderdesk_migrator",
    ):
        raise RuntimeError(
            "Browser fixtures require the test database maintenance role."
        )

fixture_file = Path("var/frontend_browser_fixture.json")
action = os.environ["FRONTEND_FIXTURE_ACTION"]
if action == "create":
    if fixture_file.exists():
        raise RuntimeError("Existing browser fixture must be cleaned first.")
    nonce = uuid4().hex
    email = f"browser-{nonce}@example.test"
    credential = f"Synthetic-{uuid4().hex}"
    # Write identities first so cleanup remains possible even after interruption.
    data = {
        "email": email,
        "password": credential,
        "user": str(uuid4()),
        "a": str(uuid4()),
        "b": str(uuid4()),
        "peer_budgets": {},
        "ready": str(uuid4()),
        "blocked": str(uuid4()),
        "foreign": str(uuid4()),
    }
    fixture_file.parent.mkdir(parents=True, exist_ok=True)
    fixture_file.write_text(json.dumps(data), encoding="utf-8")
    with transaction.atomic():
        user = User.objects.create_user(
            id=data["user"], email=email, password=credential
        )
        alpha = Organization.objects.create(id=data["a"], name="Browser Alpha Supply")
        beta = Organization.objects.create(id=data["b"], name="Browser Beta Supply")
        for organization in (alpha, beta):
            Membership.objects.create(
                user=user, organization=organization, role=MembershipRole.VIEWER
            )
        CatalogItem.objects.bulk_create(
            [
                CatalogItem(
                    organization=alpha,
                    sku=f"ALPHA-{number:03}",
                    description="Synthetic industrial fitting",
                    is_active=number != 51,
                )
                for number in range(52)
            ]
            + [
                CatalogItem(
                    organization=beta,
                    sku="BETA-ONLY",
                    description='<img src=x onerror="window.injected=true">',
                )
            ]
        )
        item = CatalogItem.objects.create(
            organization=alpha, sku="0001.Mixed-Case", description="Synthetic match"
        )
        ready = DraftOrder.objects.create(
            id=data["ready"],
            organization=alpha,
            initiating_user=user,
            customer_name="Browser Ready Customer",
            customer_reference="00042",
            original_intake_text='<img src=x onerror="window.injected=true">',
        )
        blocked = DraftOrder.objects.create(
            id=data["blocked"], organization=alpha, initiating_user=user
        )
        DraftOrder.objects.create(
            id=data["foreign"],
            organization=beta,
            initiating_user=user,
            customer_name="FOREIGN-DRAFT-PRIVATE",
        )
        DraftOrder.objects.bulk_create(
            [
                DraftOrder(
                    organization=alpha,
                    initiating_user=user,
                    customer_name=f"Browser draft {number:03}",
                )
                for number in range(51)
            ]
        )
        DraftOrderLine.objects.bulk_create(
            [
                DraftOrderLine(
                    organization=alpha,
                    order=ready,
                    position=number,
                    requested_sku="0001.Mixed-Case",
                    requested_description="Manual requested fitting",
                    quantity="999999999.999" if number == 52 else "1.234",
                    unit="ea",
                    catalogue_item=item,
                    catalogue_sku_snapshot=item.sku,
                    catalogue_description_snapshot=item.description,
                )
                for number in range(1, 53)
            ]
        )
        DraftOrderLine.objects.create(
            organization=alpha,
            order=blocked,
            position=1,
            requested_sku="Unmatched request",
            quantity=None,
        )
elif action in (
    "revoke",
    "cleanup",
    "admin",
    "viewer",
    "deactivate",
    "reactivate",
    "assert_conversion",
    "assert_no_conversion",
):
    if fixture_file.exists():
        data = json.loads(fixture_file.read_text(encoding="utf-8"))
        with transaction.atomic():
            if action == "revoke":
                Membership.objects.filter(user_id=data["user"]).update(is_active=False)
            elif action in ("admin", "viewer", "deactivate", "reactivate"):
                Organization.objects.select_for_update().get(pk=data["a"])
                if action in ("admin", "viewer"):
                    Membership.objects.filter(
                        user_id=data["user"], organization_id=data["a"]
                    ).update(role=action)
                else:
                    CatalogItem.objects.filter(
                        organization_id=data["a"], sku="0001.Mixed-Case"
                    ).update(is_active=action == "reactivate")
            elif action == "assert_no_conversion":
                unittest.TestCase().assertEqual(
                    PurchaseOrder.objects.filter(source_draft_id=data["ready"]).count(),
                    0,
                )
            elif action == "assert_conversion":
                orders = PurchaseOrder.objects.filter(source_draft_id=data["ready"])
                checks = unittest.TestCase()
                checks.assertEqual(orders.count(), 1)
                order = orders.get()
                checks.assertEqual(str(order.organization_id), data["a"])
                checks.assertEqual(str(order.pk), os.environ["FRONTEND_ORDER_ID"])
                checks.assertEqual(
                    DraftOrder.objects.get(pk=data["ready"]).status, "converted"
                )
                checks.assertEqual(order.lines.count(), 52)
                checks.assertEqual(
                    str(order.lines.get(line_number=1).quantity), "1.2340"
                )
                checks.assertEqual(
                    str(order.lines.get(line_number=52).quantity), "999999999.9990"
                )
                checks.assertEqual(
                    set(order.lines.values_list("sku", flat=True)), {"0001.Mixed-Case"}
                )
            else:
                # Remove only this user's sessions and this run's identities.
                for session in Session.objects.all().iterator():
                    if session.get_decoded().get("_auth_user_id") == data["user"]:
                        session.delete()
                keys = [login_bucket_key("email", data["email"])]
                keys.extend(
                    key
                    for key, created in data.get("peer_budgets", {}).items()
                    if created
                )
                LoginAttemptBucket.objects.filter(key__in=keys).delete()
                workspace_ids = [data["a"], data["b"]]
                PurchaseOrderLine.objects.filter(
                    order__organization_id__in=workspace_ids
                ).delete()
                PurchaseOrder.objects.filter(organization_id__in=workspace_ids).delete()
                DraftOrderLine.objects.filter(
                    organization_id__in=workspace_ids
                ).delete()
                DraftOrder.objects.filter(organization_id__in=workspace_ids).delete()
                CatalogItem.objects.filter(
                    organization_id__in=[data["a"], data["b"]]
                ).delete()
                Membership.objects.filter(user_id=data["user"]).delete()
                Organization.objects.filter(pk__in=[data["a"], data["b"]]).delete()
                User.objects.filter(pk=data["user"]).delete()
        if action == "cleanup":
            fixture_file.unlink()
else:
    raise RuntimeError("Unknown fixture action.")
print(f"Synthetic browser fixtures: {action} complete.")
