"""Seed repeat-safe incoming recovery evidence only in an owned synthetic run."""

import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local_production")
sys.path.insert(0, "/app")
django.setup()

from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.db import connection  # noqa: E402

from apps.accounts.models import User  # noqa: E402
from apps.orders import incoming, selectors  # noqa: E402
from apps.orders.extraction_apply import (  # noqa: E402
    apply_extraction,
    candidates,
    result_revision,
)
from apps.orders.extraction_services import (  # noqa: E402
    enqueue_extraction,
    process_extraction,
)
from apps.orders.revisions import draft_revision  # noqa: E402
from apps.organizations.transactions import tenant_scope  # noqa: E402


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main():
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user, session_user")
        if cursor.fetchone() != ("test_orderdesk", "orderdesk_app", "orderdesk_app"):
            raise RuntimeError(
                "Incoming recovery seed requires synthetic runtime identity."
            )
    root = Path("/run-state")
    fixture = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    state_path = root / "workflow.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    plan_path = root / "incoming-plan.json"
    if not plan_path.exists():
        save(
            plan_path, {key: str(uuid4()) for key in ("upload", "link", "application")}
        )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    actor = User.objects.get(pk=fixture["user"])
    workspace = UUID(fixture["a"])
    raw = b"sku,quantity,unit\n00042,1.250,case\n"
    document, _ = incoming.receive(
        actor=actor,
        organization_id=workspace,
        operation_key=UUID(plan["upload"]),
        upload=lambda: SimpleUploadedFile("restore-incoming.csv", raw),
    )
    document_id = UUID(str(document["id"]))
    link_payload = {
        "operation_key": plan["link"],
        "customer_name": "Synthetic incoming recovery",
        "customer_reference": "RESTORE-00042",
    }
    linked, _ = incoming.link(
        actor=actor,
        organization_id=workspace,
        document_id=document_id,
        data=lambda: link_payload,
    )
    if "apply" in plan:
        # A later customer recovery step may have converted the linked draft.
        # Reuse the saved job/receipt instead of requesting new processing.
        job_id = UUID(plan["apply"]["job_id"])
    else:
        job_id, _ = enqueue_extraction(
            actor=actor,
            organization_id=workspace,
            order_id=None,
            document_id=document_id,
            materialize=lambda job: job.pk,
        )
    if (
        process_extraction(actor=actor, organization_id=workspace, job_id=job_id)
        != "succeeded"
    ):
        raise RuntimeError("Synthetic incoming extraction did not complete.")
    if "apply" not in plan:
        with tenant_scope(user=actor, workspace_id=workspace):
            job = selectors.get_extraction_job_by_id(workspace, job_id)
            draft = selectors.get_draft_order(workspace, UUID(str(linked["draft"])))
            plan["apply"] = {
                "operation_key": plan["application"],
                "job_id": str(job_id),
                "draft_id": str(linked["draft"]),
                "result_revision": result_revision(job),
                "expected_draft_revision": draft_revision(draft),
                "mappings": [
                    {
                        "candidate_id": candidates(job)[0]["candidate_id"],
                        "action": "create",
                        "position": 1,
                        "fields": ["sku", "quantity", "unit"],
                        "corrections": {},
                    }
                ],
            }
        save(plan_path, plan)
    receipt, _ = apply_extraction(
        actor=actor,
        organization_id=workspace,
        order_id=None,
        document_id=document_id,
        data=plan["apply"],
    )
    state["incoming"] = {
        "workspace": str(workspace),
        "foreign_workspace": fixture["b"],
        "document": {**document, "sha256": hashlib.sha256(raw).hexdigest()},
        "draft_id": str(linked["draft"]),
        "job_id": str(job_id),
        "application_id": receipt["application_id"],
        "link_payload": link_payload,
        "apply_payload": plan["apply"],
    }
    save(state_path, state)
    print(
        "PASS: synthetic incoming source, link and applied proposal "
        "recovery evidence prepared."
    )


if __name__ == "__main__":
    main()
