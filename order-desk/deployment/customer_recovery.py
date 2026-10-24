"""Extend an owned incoming recovery fixture with customer identity and snapshot."""

import json
from pathlib import Path
from uuid import UUID, uuid4

from django.db import connection

# incoming_recovery establishes Django before importing application code.
from incoming_recovery import save

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.catalog.services import create_catalog_item
from apps.customers.confirmation import confirm, fingerprint, selected_reference
from apps.customers.models import OrderCustomerSnapshot
from apps.customers.services import save_reference
from apps.orders import selectors
from apps.orders.revisions import draft_revision
from apps.orders.services import (
    attach_catalogue_item_to_draft_order_line,
    convert_draft_to_purchase_order,
)
from apps.organizations.transactions import tenant_scope


def main():
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user, session_user")
        if cursor.fetchone() != ("test_orderdesk", "orderdesk_app", "orderdesk_app"):
            raise RuntimeError("Customer recovery requires synthetic runtime identity.")
    root = Path("/run-state")
    fixture = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    state = json.loads((root / "workflow.json").read_text(encoding="utf-8"))
    path = root / "customer-plan.json"
    if not path.exists():
        save(
            path,
            {kind: str(uuid4()) for kind in ("account", "site", "alias", "confirm")},
        )
    plan = json.loads(path.read_text(encoding="utf-8"))
    actor = User.objects.get(pk=fixture["user"])
    workspace = UUID(fixture["a"])
    draft_id = UUID(state["incoming"]["draft_id"])
    account = save_reference(
        actor=actor,
        organization_id=workspace,
        kind="account",
        operation_key=UUID(plan["account"]),
        data=lambda: {
            "code": "RECOVERY-00042",
            "display_name": "Synthetic recovery confirmed customer",
            "destination_id": "000007",
            "requires_location": True,
        },
    )
    site = save_reference(
        actor=actor,
        organization_id=workspace,
        kind="location",
        customer_id=UUID(account["id"]),
        operation_key=UUID(plan["site"]),
        data=lambda: {
            "code": "00B",
            "display_name": "Synthetic site",
            "destination_id": "000020",
        },
    )
    alias = save_reference(
        actor=actor,
        organization_id=workspace,
        kind="alias",
        customer_id=UUID(account["id"]),
        operation_key=UUID(plan["alias"]),
        data=lambda: {
            "value": "Recovery.Exact",
            "provenance": "Synthetic restore fixture approval",
        },
    )
    if "confirmation" not in plan:
        with tenant_scope(user=actor, workspace_id=workspace):
            _, _, reference = selected_reference(workspace, account["id"], site["id"])
            draft = selectors.get_draft_order(workspace, draft_id)
            plan["confirmation"] = {
                "operation_key": plan["confirm"],
                "customer_id": account["id"],
                "location_id": site["id"],
                "reference_revision": fingerprint(reference),
                "expected_draft_revision": draft_revision(draft),
            }
        save(path, plan)
    decision, _ = confirm(
        actor=actor,
        organization_id=workspace,
        draft_id=draft_id,
        data=lambda: plan["confirmation"],
    )
    with tenant_scope(user=actor, workspace_id=workspace):
        item_id = (
            CatalogItem.objects.filter(organization_id=workspace, sku="00042")
            .values_list("pk", flat=True)
            .first()
        )
    if item_id is None:
        item_id = create_catalog_item(
            actor=actor,
            organization_id=workspace,
            data={"sku": "00042", "description": "Synthetic recovery selected product"},
            materialize=lambda item: item.pk,
        )
    with tenant_scope(user=actor, workspace_id=workspace):
        draft = selectors.get_draft_order(workspace, draft_id)
        line = selectors.draft_lines_for_order(workspace, draft_id).get()
        needs_attachment = line.catalogue_item_id is None
        line_id, revision = line.pk, draft_revision(draft)
    if needs_attachment:
        attach_catalogue_item_to_draft_order_line(
            actor=actor,
            organization_id=workspace,
            order_id=draft_id,
            line_id=line_id,
            catalogue_item_id=item_id,
            expected_revision=revision,
        )
    with tenant_scope(user=actor, workspace_id=workspace):
        revision = draft_revision(selectors.get_draft_order(workspace, draft_id))
    order_id, _ = convert_draft_to_purchase_order(
        actor=actor,
        organization_id=workspace,
        order_id=draft_id,
        data={},
        expected_revision=revision,
        materialize=lambda row: row.pk,
    )
    with tenant_scope(user=actor, workspace_id=workspace):
        snapshot = OrderCustomerSnapshot.objects.get(
            organization_id=workspace, order_id=order_id
        )
        state["customer"] = {
            "workspace": str(workspace),
            "account_id": account["id"],
            "site_id": site["id"],
            "alias_id": alias["id"],
            "receipt_key": plan["account"],
            "draft_id": str(draft_id),
            "decision_id": decision["id"],
            "confirmation": plan["confirmation"],
            "order_id": str(order_id),
            "snapshot_id": str(snapshot.pk),
            "payload": snapshot.payload,
        }
    save(root / "workflow.json", state)
    print(
        "PASS: customer reference receipts, confirmed site and frozen order prepared."
    )


if __name__ == "__main__":
    main()
