"""One isolated maintenance fixture; browser requests always use restricted API."""

import base64
import json
import secrets
from pathlib import Path
from uuid import uuid4

from django.db import connection, transaction

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.orders.models import PurchaseOrder
from apps.orders.tests.pdf_fixtures import supported_pdf
from apps.organizations.models import Membership, MembershipRole, Organization

with connection.cursor() as cursor:
    cursor.execute("SELECT current_database(),current_user,session_user")
    if cursor.fetchone() != (
        "test_orderdesk",
        "orderdesk_migrator",
        "orderdesk_migrator",
    ):
        raise RuntimeError(
            "Synthetic fixtures require test_orderdesk maintenance role."
        )
destination = Path("/run-state/fixture.json")
if destination.exists():
    raise RuntimeError("Preserve/review existing fixtures; do not recreate them.")
with transaction.atomic():
    credential = secrets.token_urlsafe(32)
    user = User.objects.create_user(
        email=f"deployment-{uuid4().hex}@example.test", password=credential
    )
    a = Organization.objects.create(name="Deployment Alpha")
    b = Organization.objects.create(name="Deployment Beta")
    Membership.objects.create(user=user, organization=a, role=MembershipRole.ADMIN)
    Membership.objects.create(user=user, organization=b, role=MembershipRole.VIEWER)
    role_accounts = {}
    for role in (MembershipRole.VIEWER, MembershipRole.REVIEWER):
        password = secrets.token_urlsafe(32)
        member = User.objects.create_user(
            email=f"deployment-{role}-{uuid4().hex}@example.test", password=password
        )
        Membership.objects.create(user=member, organization=a, role=role)
        role_accounts[role] = {"email": member.email, "password": password}
    item = CatalogItem.objects.create(
        organization=a, sku="0001.Mixed-Case", description="Synthetic fitting"
    )
    CatalogItem.objects.create(
        organization=b, sku="PRIVATE-BETA", description="Foreign product"
    )
    viewer_order = PurchaseOrder.objects.create(
        organization=b,
        created_by=user,
        customer_name="Viewer-only fixture",
        purchase_order_number=f"VIEWER-{uuid4().hex}",
    )
    destination.write_text(
        json.dumps(
            {
                "email": user.email,
                "password": credential,
                "user": str(user.pk),
                "a": str(a.pk),
                "b": str(b.pk),
                "item": str(item.pk),
                "viewer_order": str(viewer_order.pk),
                "pdf_base64": base64.b64encode(supported_pdf()).decode("ascii"),
                "role_accounts": role_accounts,
            }
        ),
        encoding="utf-8",
    )
print("Created isolated synthetic fixture; credentials remain private.")
