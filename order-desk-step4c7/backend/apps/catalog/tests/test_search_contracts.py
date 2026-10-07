"""Strict catalogue search/lookup contracts and lazy SQL shape without SQL."""

from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.db import connection
from django.http import QueryDict
from django.test import SimpleTestCase, override_settings
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.catalog.models import CatalogItem
from apps.catalog.pagination import CatalogPagination
from apps.catalog.query_params import parse_exact_sku, parse_list_query
from apps.catalog.selectors import catalog_item_by_sku, catalog_items_for_workspace
from apps.catalog.serializers import CatalogItemCreateSerializer


def parameters(**values) -> QueryDict:
    query = QueryDict("", mutable=True)
    for key, value in values.items():
        query.setlist(key, value if isinstance(value, list) else [value])
    return query


class CatalogSearchQueryContractTests(SimpleTestCase):
    def test_omitted_filters_preserve_both_statuses_and_unfiltered_search(self):
        query = parse_list_query(parameters())
        self.assertIsNone(query.q)
        self.assertIsNone(query.is_active)

    def test_search_strips_edges_and_preserves_one_literal_term(self):
        for value in ("  Washer assembly \t", " %_'\\ ", "  é中文  "):
            with self.subTest(value=value):
                self.assertEqual(parse_list_query(parameters(q=value)).q, value.strip())

    def test_search_uses_normalized_character_limit(self):
        self.assertEqual(
            parse_list_query(parameters(q=" " + "é" * 200 + "\t")).q, "é" * 200
        )
        with self.assertRaises(ValidationError) as error:
            parse_list_query(parameters(q="é" * 201))
        self.assertIn("q", error.exception.detail)

    def test_blank_search_and_driver_invalid_text_are_field_errors(self):
        for value in ("", " \t\n", "part\x00", "part\ud800"):
            with (
                self.subTest(value=repr(value)),
                self.assertRaises(ValidationError) as error,
            ):
                parse_list_query(parameters(q=value))
            self.assertEqual(set(error.exception.detail), {"q"})

    def test_active_filter_accepts_exact_lowercase_values(self):
        for value, expected in (("true", True), ("false", False)):
            with self.subTest(value=value):
                query = parse_list_query(parameters(q=" washer ", is_active=value))
                self.assertEqual(query.q, "washer")
                self.assertIs(query.is_active, expected)

    def test_active_filter_rejects_other_spellings_and_blank(self):
        for value in ("", "TRUE", "False", "1", "0", " true ", "null"):
            with self.subTest(value=value), self.assertRaises(ValidationError) as error:
                parse_list_query(parameters(is_active=value))
            self.assertEqual(set(error.exception.detail), {"is_active"})

    def test_every_list_parameter_rejects_repetition_even_identical_values(self):
        for key, value in (("page", "1"), ("q", "part"), ("is_active", "true")):
            with self.subTest(key=key), self.assertRaises(ValidationError) as error:
                parse_list_query(parameters(**{key: [value, value]}))
            self.assertEqual(
                error.exception.detail[key], ["Provide this query parameter once."]
            )

    def test_list_unknown_scope_ordering_and_page_size_parameters_are_rejected(self):
        for key in (
            "sku",
            "search",
            "organization_id",
            "user_id",
            "ordering",
            "page_size",
        ):
            with self.subTest(key=key), self.assertRaises(ValidationError) as error:
                parse_list_query(parameters(**{key: "forged"}))
            self.assertEqual(error.exception.detail[key], ["Unknown query parameter."])

    def test_page_value_errors_remain_the_paginators_responsibility(self):
        for value in ("", "0", "last", "1.5", "9" * 5000):
            with self.subTest(value=value[:10]):
                query = parse_list_query(parameters(page=value, q="part"))
                self.assertEqual(query.q, "part")

    def test_exact_sku_is_required_and_nonblank(self):
        for query in (parameters(), parameters(sku=""), parameters(sku=" \t\n")):
            with self.subTest(query=query), self.assertRaises(ValidationError) as error:
                parse_exact_sku(query)
            self.assertEqual(set(error.exception.detail), {"sku"})

    def test_exact_sku_uses_creation_normalization_and_preserves_case(self):
        for value in ("  000Ab/P-1.x \t", "%_'\\", "é中文"):
            with self.subTest(value=value):
                serializer = CatalogItemCreateSerializer(data={"sku": value})
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(
                    parse_exact_sku(parameters(sku=value)),
                    serializer.validated_data["sku"],
                )

    def test_exact_sku_rejects_repetition_and_additional_query_parameters(self):
        for query, field in (
            (parameters(sku=["PART-001", "PART-001"]), "sku"),
            (parameters(sku="PART-001", page="1"), "page"),
            (parameters(sku="PART-001", q="part"), "q"),
            (parameters(sku="PART-001", is_active="true"), "is_active"),
            (
                parameters(sku="PART-001", organization_id=str(uuid4())),
                "organization_id",
            ),
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError) as error:
                parse_exact_sku(query)
            self.assertIn(field, error.exception.detail)

    def test_exact_sku_has_the_actual_models_unbounded_text_limit(self):
        self.assertIsNone(CatalogItem._meta.get_field("sku").max_length)
        value = "Part-" + "x" * 5000
        self.assertEqual(parse_exact_sku(parameters(sku=value)), value)

    def test_exact_sku_rejects_driver_invalid_text_before_query_evaluation(self):
        for value in ("part\x00", "part\udfff"):
            with (
                self.subTest(value=repr(value)),
                self.assertRaises(ValidationError) as error,
            ):
                parse_exact_sku(parameters(sku=value))
            self.assertEqual(set(error.exception.detail), {"sku"})


class CatalogSearchSelectorContractTests(SimpleTestCase):
    def test_search_or_is_grouped_under_the_organization_and_preserves_laziness(self):
        organization_id = uuid4()
        items = catalog_items_for_workspace(organization_id=organization_id, q="part")
        self.assertIsNone(items._result_cache)
        self.assertEqual(items.query.where.connector, "AND")
        organization, search = items.query.where.children
        self.assertEqual(organization.lhs.target.attname, "organization_id")
        self.assertEqual(organization.rhs, organization_id)
        self.assertEqual(search.connector, "OR")
        self.assertEqual(
            {lookup.lhs.target.attname for lookup in search.children},
            {"sku", "description"},
        )
        self.assertTrue(
            all(lookup.lookup_name == "icontains" for lookup in search.children)
        )
        self.assertEqual(items.query.order_by, ("sku", "id"))

    def test_both_active_filter_values_add_a_database_predicate(self):
        for active in (True, False):
            with self.subTest(active=active):
                items = catalog_items_for_workspace(
                    organization_id=uuid4(), q="part", is_active=active
                )
                lookup = items.query.where.children[-1]
                self.assertEqual(lookup.lhs.target.attname, "is_active")
                self.assertIs(lookup.rhs, active)
                self.assertIsNone(items._result_cache)

    def test_literal_search_is_bound_and_like_metacharacters_are_escaped(self):
        term = "%_'\\!"
        items = catalog_items_for_workspace(organization_id=uuid4(), q=term)
        sql, bound = items.query.get_compiler(connection=connection).as_sql()
        self.assertNotIn(term, sql)
        self.assertEqual(bound[1:], ("%\\%\\_'\\\\!%", "%\\%\\_'\\\\!%"))
        self.assertIn(" OR ", sql)
        self.assertIn(" AND ", sql)

    def test_exact_selector_is_lazy_tenant_and_case_preserving_equality(self):
        organization_id = uuid4()
        sku = "000Ab/P-1.x"
        items = catalog_item_by_sku(organization_id=organization_id, sku=sku)
        self.assertIsNone(items._result_cache)
        lookups = {
            lookup.lhs.target.attname: lookup for lookup in items.query.where.children
        }
        self.assertEqual(set(lookups), {"organization_id", "sku"})
        self.assertEqual(lookups["organization_id"].rhs, organization_id)
        self.assertEqual(lookups["sku"].lookup_name, "exact")
        self.assertEqual(lookups["sku"].rhs, sku)


@override_settings(ALLOWED_HOSTS=["testserver"])
class CatalogSearchPaginationContractTests(SimpleTestCase):
    def test_filtered_pagination_links_retain_search_status_and_workspace(self):
        path = f"/api/v1/workspaces/{uuid4()}/catalog/items/"
        query = {"q": "part & _%", "is_active": "false"}
        first = CatalogPagination()
        rows = first.paginate_queryset(
            list(range(51)), Request(APIRequestFactory().get(path, query))
        )
        self.assertEqual(rows, list(range(50)))
        next_link = urlsplit(first.get_paginated_response(rows).data["next"])
        self.assertEqual(next_link.path, path)
        self.assertEqual(
            parse_qs(next_link.query),
            {"q": [query["q"]], "is_active": ["false"], "page": ["2"]},
        )
        second = CatalogPagination()
        remainder = second.paginate_queryset(
            list(range(51)),
            Request(APIRequestFactory().get(path, {**query, "page": "2"})),
        )
        self.assertEqual(remainder, [50])
        previous = urlsplit(second.get_paginated_response(remainder).data["previous"])
        self.assertEqual(previous.path, path)
        self.assertEqual(
            parse_qs(previous.query), {"q": [query["q"]], "is_active": ["false"]}
        )

    def test_search_filters_do_not_change_fixed_bounds_or_invalid_page_contract(self):
        path = f"/api/v1/workspaces/{uuid4()}/catalog/items/"
        for page in ("", "0", "last", "1.5", "2"):
            request = Request(
                APIRequestFactory().get(
                    path, {"q": "part", "is_active": "true", "page": page}
                )
            )
            with self.subTest(page=page), self.assertRaises(NotFound) as error:
                CatalogPagination().paginate_queryset([], request)
            self.assertEqual(str(error.exception.detail), "Invalid page.")
