"""Draft read selectors and response contracts without a database connection."""

from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.orders.models import DraftOrder, DraftOrderLine
from apps.orders.pagination import DraftOrderPagination, validate_draft_query
from apps.orders.selectors import draft_lines_for_order, draft_orders_for_workspace
from apps.orders.serializers import (
    DraftOrderDetailSerializer,
    DraftOrderLineReadSerializer,
    DraftOrderSummarySerializer,
)


class DraftSelectorContracts(SimpleTestCase):
    def test_list_is_lazy_scoped_counted_and_deterministically_ordered(self) -> None:
        workspace_id = uuid4()
        orders = draft_orders_for_workspace(workspace_id)

        self.assertIsNone(orders._result_cache)
        self.assertEqual(orders.query.order_by, ("-created_at", "-id"))
        self.assertIn("line_count", orders.query.annotations)
        self.assertEqual(len(orders.query.where.children), 1)
        lookup = orders.query.where.children[0]
        self.assertEqual(lookup.lhs.target.attname, "organization_id")
        self.assertEqual(lookup.rhs, workspace_id)

    def test_lines_are_lazy_and_filter_workspace_and_parent(self) -> None:
        workspace_id, order_id = uuid4(), uuid4()
        lines = draft_lines_for_order(workspace_id, order_id)

        self.assertIsNone(lines._result_cache)
        self.assertEqual(lines.query.order_by, ("position", "id"))
        lookups = {
            lookup.lhs.target.attname: lookup.rhs
            for lookup in lines.query.where.children
        }
        self.assertEqual(
            lookups,
            {"organization_id": workspace_id, "order_id": order_id},
        )


class DraftSerializerContracts(SimpleTestCase):
    def test_summary_has_only_scalar_allowlist_and_no_intake_text(self) -> None:
        order = DraftOrder(
            organization_id=uuid4(),
            initiating_user_id=uuid4(),
            original_intake_text="Private original request",
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        order.line_count = 2
        body = DraftOrderSummarySerializer(order).data

        self.assertEqual(
            set(body),
            {
                "id",
                "organization_id",
                "status",
                "source_type",
                "customer_name",
                "customer_reference",
                "initiating_user_id",
                "created_at",
                "updated_at",
                "line_count",
            },
        )
        self.assertEqual(body["line_count"], 2)
        self.assertEqual(body["initiating_user_id"], str(order.initiating_user_id))
        self.assertNotIn("original_intake_text", body)
        self.assertEqual(order._state.fields_cache, {})

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_detail_adds_bounded_intake_text_and_reversed_lines_url(self) -> None:
        workspace_id = uuid4()
        order = DraftOrder(
            organization_id=workspace_id,
            initiating_user_id=uuid4(),
            original_intake_text="Original request",
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        order.line_count = 0
        path = f"/api/v1/workspaces/{workspace_id}/draft-orders/{order.pk}/"
        request = Request(APIRequestFactory().get(path))
        body = DraftOrderDetailSerializer(order, context={"request": request}).data

        self.assertEqual(
            set(body),
            set(DraftOrderSummarySerializer(order).data)
            | {"original_intake_text", "lines_url"},
        )
        self.assertEqual(body["original_intake_text"], "Original request")
        self.assertEqual(
            body["lines_url"],
            f"http://testserver{path}lines/",
        )
        self.assertNotIn("lines", body)
        self.assertEqual(order._state.fields_cache, {})

    def test_line_preserves_decimal_null_and_catalogue_snapshots(self) -> None:
        fields = {
            "id",
            "organization_id",
            "order_id",
            "position",
            "requested_sku",
            "requested_description",
            "quantity",
            "unit",
            "catalogue_item_id",
            "catalogue_sku_snapshot",
            "catalogue_description_snapshot",
            "created_at",
            "updated_at",
        }
        line = DraftOrderLine(
            organization_id=uuid4(),
            order_id=uuid4(),
            position=3,
            requested_description="Original requested part",
            quantity=None,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        body = DraftOrderLineReadSerializer(line).data
        self.assertEqual(set(body), fields)
        self.assertIsNone(body["quantity"])
        self.assertIsNone(body["catalogue_item_id"])
        self.assertEqual(line._state.fields_cache, {})

        line.quantity = Decimal("1.250")
        line.catalogue_item_id = uuid4()
        line.catalogue_sku_snapshot = "OLD-SKU"
        line.catalogue_description_snapshot = "Old description"
        body = DraftOrderLineReadSerializer(line).data
        self.assertEqual(body["quantity"], "1.250")
        self.assertEqual(body["catalogue_item_id"], str(line.catalogue_item_id))
        self.assertEqual(body["catalogue_description_snapshot"], "Old description")
        self.assertEqual(line._state.fields_cache, {})


@override_settings(ALLOWED_HOSTS=["testserver"])
class DraftPaginationContracts(SimpleTestCase):
    def setUp(self) -> None:
        self.path = f"/api/v1/workspaces/{uuid4()}/draft-orders/"

    def request(self, query: str = "") -> Request:
        return Request(APIRequestFactory().get(self.path + query))

    def test_fixed_fifty_with_bounded_links_and_empty_result(self) -> None:
        paginator = DraftOrderPagination()
        first = paginator.paginate_queryset(list(range(55)), self.request())
        self.assertEqual(first, list(range(50)))
        next_link = urlsplit(paginator.get_paginated_response(first).data["next"])
        self.assertEqual(next_link.path, self.path)
        self.assertEqual(parse_qs(next_link.query), {"page": ["2"]})

        paginator = DraftOrderPagination()
        second = paginator.paginate_queryset(list(range(55)), self.request("?page=2"))
        self.assertEqual(second, list(range(50, 55)))
        previous = urlsplit(paginator.get_paginated_response(second).data["previous"])
        self.assertEqual(previous.path, self.path)
        self.assertEqual(parse_qs(previous.query), {})

        paginator = DraftOrderPagination()
        empty = paginator.paginate_queryset([], self.request())
        self.assertEqual(
            paginator.get_paginated_response(empty).data,
            {"count": 0, "next": None, "previous": None, "results": []},
        )

    def test_repeated_or_unsupported_query_keys_are_400(self) -> None:
        for query in (
            "?page=1&page=2",
            "?page=1&page=1",
            "?page_size=1000",
            "?organization_id=" + str(uuid4()),
            "?ordering=position",
            "?status=draft",
        ):
            with self.subTest(query=query), self.assertRaises(ValidationError):
                DraftOrderPagination().paginate_queryset([], self.request(query))
        with self.assertRaises(ValidationError):
            validate_draft_query(self.request("?page=1").query_params, allow_page=False)

    def test_invalid_and_unavailable_pages_keep_existing_404(self) -> None:
        for query in ("?page=", "?page=0", "?page=-1", "?page=last", "?page=2"):
            with self.subTest(query=query), self.assertRaises(NotFound) as error:
                DraftOrderPagination().paginate_queryset([], self.request(query))
            self.assertEqual(str(error.exception.detail), "Invalid page.")
