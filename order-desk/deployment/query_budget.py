"""Restricted-runtime application query counts; excludes session authentication."""

import json
import os
from pathlib import Path
from uuid import UUID

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local_production")
django.setup()

from django.db import connection  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

from apps.accounts.models import User  # noqa: E402
from apps.orders.views import (  # noqa: E402
    DraftOrderListCreateView,
    DraftOrderReadinessView,
    OrderDetailView,
    OrderQueueView,
)

fixture = json.loads(Path("/run-state/fixture.json").read_text(encoding="utf-8"))
workflow = json.loads(Path("/run-state/workflow.json").read_text(encoding="utf-8"))
capacity = Path("/run-state/performance-fixture.json")
workspace = fixture["a"]
if capacity.exists():
    workload = json.loads(capacity.read_text(encoding="ascii"))
    workspace = workload["workspace"]
    workflow.update(draft=workload["draft"], source=workload["source"])
user = User.objects.get(pk=fixture["user"])
factory = APIRequestFactory()
report = {}
for name, view, order in (
    ("drafts", DraftOrderListCreateView, None),
    ("order_queue", OrderQueueView, None),
    ("source_order", OrderDetailView, workflow["source"]),
    ("readiness", DraftOrderReadinessView, workflow["draft"]),
):
    request = factory.get("/", HTTP_HOST="orderdesk.localhost", secure=True)
    force_authenticate(request, user=user)
    with CaptureQueriesContext(connection) as queries:
        kwargs = {"workspace_id": UUID(workspace)}
        if order is not None:
            kwargs["order_id"] = UUID(order)
        response = view.as_view()(request, **kwargs)
        response.render()
    if response.status_code != 200:
        raise RuntimeError("Query-budget fixture failed.")
    report[name] = len(queries)
    if name == "drafts":
        counts = [query["sql"] for query in queries if "COUNT(*)" in query["sql"]]
        if len(counts) != 1 or "orders_draftorderline" in counts[0]:
            raise RuntimeError("Draft pagination count must not scan line histories.")
    if name == "order_queue":
        if any(
            table in query["sql"]
            for query in queries
            for table in ("orders_purchaseorderline", "orders_orderdocument")
        ):
            raise RuntimeError(
                "Operational queue must not load nested lines/documents."
            )
print(
    json.dumps(
        {
            "query_counts": report,
            "provisional_limit": 25,
            "excludes": "session authentication queries",
        },
        sort_keys=True,
    )
)
if max(report.values()) > 25:
    raise RuntimeError("Application query budget exceeded.")
