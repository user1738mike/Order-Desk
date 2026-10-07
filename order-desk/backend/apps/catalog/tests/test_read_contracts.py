"""Catalogue query, scalar serialization, and pagination contracts without SQL."""

from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.catalog.models import CatalogItem
from apps.catalog.pagination import CatalogPagination
from apps.catalog.selectors import catalog_items_for_workspace
from apps.catalog.serializers import CatalogItemSerializer


class CatalogReadContractTests(SimpleTestCase):
    def test_selector_is_lazy_and_explicitly_filters_authorized_organization(self):
        organization_id = uuid4()
        items = catalog_items_for_workspace(organization_id=organization_id)
        self.assertIsNone(items._result_cache)
        self.assertEqual(len(items.query.where.children), 1)
        lookup = items.query.where.children[0]
        self.assertEqual(lookup.lhs.target.attname, "organization_id")
        self.assertEqual(lookup.lookup_name, "exact")
        self.assertEqual(lookup.rhs, organization_id)

    def test_selector_orders_by_stock_code_then_uuid(self):
        items = catalog_items_for_workspace(organization_id=uuid4())
        self.assertEqual(items.query.order_by, ("sku", "id"))

    def test_selector_does_not_filter_out_inactive_catalogue_identities(self):
        items = catalog_items_for_workspace(organization_id=uuid4())
        self.assertNotIn("is_active", str(items.query.where))
        self.assertIsNone(items._result_cache)

    def test_serializer_has_exact_public_field_allowlist(self):
        self.assertEqual(
            tuple(CatalogItemSerializer().fields),
            (
                "id",
                "organization_id",
                "sku",
                "description",
                "is_active",
                "created_at",
                "updated_at",
            ),
        )

    def test_serializer_fields_are_read_only_and_ignore_client_assignments(self):
        serializer = CatalogItemSerializer(
            data={"organization_id": str(uuid4()), "sku": "REASSIGN", "is_active": True}
        )
        self.assertTrue(all(field.read_only for field in serializer.fields.values()))
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data, {})

    def test_serializer_uses_fk_scalar_without_relation_queries_or_sku_changes(self):
        organization_id = uuid4()
        now = timezone.now()
        item = CatalogItem(
            organization_id=organization_id,
            sku="000Ab/P-1.x",
            description="Synthetic part",
            is_active=False,
            created_at=now,
            updated_at=now,
        )
        self.assertNotIn("organization", item._state.fields_cache)
        body = CatalogItemSerializer(item).data
        self.assertEqual(body["id"], str(item.pk))
        self.assertEqual(body["organization_id"], str(organization_id))
        self.assertEqual(body["sku"], "000Ab/P-1.x")
        self.assertFalse(body["is_active"])
        self.assertNotIn("organization", item._state.fields_cache)


@override_settings(ALLOWED_HOSTS=["testserver"])
class CatalogPaginationContractTests(SimpleTestCase):
    def setUp(self) -> None:
        self.path = f"/api/v1/workspaces/{uuid4()}/catalog/items/"

    def request(self, query="") -> Request:
        return Request(APIRequestFactory().get(self.path + query))

    def test_omitted_page_and_page_one_use_fixed_fifty_item_first_page(self):
        for query in ("", "?page=1"):
            with self.subTest(query=query):
                pagination = CatalogPagination()
                rows = pagination.paginate_queryset(
                    list(range(55)), self.request(query)
                )
                self.assertEqual(rows, list(range(50)))
                body = pagination.get_paginated_response(rows).data
                self.assertEqual(body["count"], 55)
                self.assertIsNone(body["previous"])

    def test_second_page_returns_remainder_with_links_on_same_workspace_route(self):
        pagination = CatalogPagination()
        rows = pagination.paginate_queryset(list(range(55)), self.request("?page=2"))
        self.assertEqual(rows, list(range(50, 55)))
        body = pagination.get_paginated_response(rows).data
        self.assertIsNone(body["next"])
        previous = urlsplit(body["previous"])
        self.assertEqual(previous.path, self.path)
        self.assertEqual(parse_qs(previous.query), {})

    def test_empty_catalogue_returns_one_empty_first_page(self):
        pagination = CatalogPagination()
        rows = pagination.paginate_queryset([], self.request())
        self.assertEqual(
            pagination.get_paginated_response(rows).data,
            {"count": 0, "next": None, "previous": None, "results": []},
        )

    def test_unsupported_parameters_cannot_change_page_size_scope_or_ordering(self):
        for query in (
            "page_size=1000",
            "organization_id=" + str(uuid4()),
            "user_id=" + str(uuid4()),
            "ordering=-sku",
            "search=part",
            "is_active=TRUE",
        ):
            with self.subTest(query=query), self.assertRaises(ValidationError) as error:
                CatalogPagination().paginate_queryset([], self.request("?" + query))
            self.assertEqual(error.exception.status_code, 400)

    def test_repeated_parameters_including_repeated_page_one_are_rejected(self):
        for query in ("page=1&page=2", "page=1&page=1", "search=a&search=b"):
            with self.subTest(query=query), self.assertRaises(ValidationError):
                CatalogPagination().paginate_queryset([], self.request("?" + query))

    def test_blank_invalid_nonpositive_and_last_alias_pages_have_stable_404(self):
        for page in ("", "0", "00", "-1", "last", "invalid", "1.5", "9" * 5000):
            request = Request(APIRequestFactory().get(self.path, {"page": page}))
            with self.subTest(page=page[:20]), self.assertRaises(NotFound) as error:
                CatalogPagination().paginate_queryset(list(range(55)), request)
            self.assertEqual(str(error.exception.detail), "Invalid page.")

    def test_unavailable_pages_have_stable_404_including_empty_catalogues(self):
        for items, page in ((list(range(55)), 3), ([], 2)):
            with self.subTest(page=page), self.assertRaises(NotFound) as error:
                CatalogPagination().paginate_queryset(
                    items, self.request(f"?page={page}")
                )
            self.assertEqual(str(error.exception.detail), "Invalid page.")
