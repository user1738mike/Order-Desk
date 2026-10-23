"""Bounded additional synthetic workload, never main/customer fixtures."""

import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from django.db import connection, transaction

from apps.accounts.models import User
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
            "Performance fixtures require isolated test maintenance role."
        )
destination = Path("/run-state/performance-fixture.json")
if destination.exists():
    raise RuntimeError("Preserve the existing workload; do not seed twice.")
fixture = json.loads(Path("/run-state/fixture.json").read_text(encoding="utf-8"))
user = User.objects.get(pk=fixture["user"], is_active=True)
with transaction.atomic():
    workspaces = []
    for index in range(2):
        workspace = Organization.objects.create(name=f"Synthetic capacity {index}")
        workspaces.append(workspace)
        Membership.objects.create(
            organization=workspace, user=user, role=MembershipRole.ADMIN
        )
        PurchaseOrder.objects.bulk_create(
            [
                PurchaseOrder(
                    organization=workspace,
                    created_by=user,
                    customer_name="Synthetic queue buyer",
                    purchase_order_number=f"QUEUE-{index}-{i:06d}",
                )
                for i in range(500)
            ]
        )
        CatalogItem.objects.bulk_create(
            [
                CatalogItem(
                    organization=workspace,
                    sku=f"CAP-{i:06d}",
                    description="Synthetic distributor fitting",
                )
                for i in range(2500)
            ]
        )
        drafts = DraftOrder.objects.bulk_create(
            [
                DraftOrder(
                    organization=workspace,
                    initiating_user=user,
                    customer_name="Synthetic capacity buyer",
                )
                for _ in range(150)
            ]
        )
        DraftOrderLine.objects.bulk_create(
            [
                DraftOrderLine(
                    organization=workspace,
                    order=draft,
                    position=i + 1,
                    requested_sku=f"CAP-{i:06d}",
                    quantity=Decimal("1.000"),
                    unit="ea",
                )
                for draft in drafts
                for i in range(20)
            ]
        )
        if index == 0:
            first_draft = drafts[0]
    order = PurchaseOrder.objects.create(
        organization=workspaces[0],
        created_by=user,
        customer_name="Synthetic capacity buyer",
        purchase_order_number=f"CAP-{uuid4().hex}",
    )
    PurchaseOrderLine.objects.bulk_create(
        [
            PurchaseOrderLine(
                organization=workspaces[0],
                order=order,
                line_number=i + 1,
                sku=f"CAP-{i:06d}",
                quantity=Decimal("1.0000"),
                unit="ea",
            )
            for i in range(100)
        ]
    )
    destination.write_text(
        json.dumps(
            {
                "workspace": str(workspaces[0].pk),
                "draft": str(first_draft.pk),
                "source": str(order.pk),
                "counts": {
                    "workspaces": 2,
                    "catalogue_items": 5000,
                    "drafts": 300,
                    "draft_lines": 6000,
                    "purchase_orders": 1001,
                    "purchase_order_lines": 100,
                },
            }
        ),
        encoding="ascii",
    )
print(
    "Created synthetic workload: 2 tenants, 5000 catalogue items, "
    "300 drafts, 6000 draft lines, 1000 queue headers and a 100-line order."
)
