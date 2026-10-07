"""Native PostgreSQL literal search, filtering, exact equality, and read scopes."""

from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemSerializer
from apps.catalog.tests.test_create_api import PUBLIC_FIELDS
from apps.catalog.tests.test_update_api import CatalogUpdateTestCase
from apps.organizations.models import Membership, Organization
from apps.organizations.selection import SELECTED_WORKSPACE_KEY


class CatalogSearchAPITests(CatalogUpdateTestCase):
    def setUp(self):
        super().setUp()
        self.lookup = reverse(
            "workspaces:catalog:by-sku", kwargs={"workspace_id": self.a.pk}
        )

    def assert_ids(self, response, ids):
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["count"], len(ids))
        self.assertEqual(
            {row["id"] for row in body["results"]}, {str(pk) for pk in ids}
        )
        self.assert_private(response)
        self.assert_clean()

    def test_sku_substring_is_case_insensitive_trimmed_and_scoped(self):
        self.assert_ids(self.client.get(self.url, {"q": "  ab/p-1  "}), {self.item.pk})

    def test_description_or_sku_matches_never_bypass_organization(self):
        CatalogItem.objects.filter(pk=self.item.pk).update(description="steel WASHER")
        CatalogItem.objects.filter(pk=self.other.pk).update(
            description="washer foreign"
        )
        second = CatalogItem.objects.create(organization=self.a, sku="Washer-002")
        self.assert_ids(
            self.client.get(self.url, {"q": "washer"}), {self.item.pk, second.pk}
        )
        self.assert_ids(self.client.get(self.url, {"q": "foreign"}), set())

    def test_percent_underscore_quotes_and_backslashes_are_literal(self):
        terms = ("100%", "part_1", "O'Reilly", "C:\\parts")
        for i, term in enumerate(terms):
            item = CatalogItem.objects.create(
                organization=self.a,
                sku=f"LITERAL-{i}",
                description="prefix " + term + " suffix",
            )
            self.assert_ids(self.client.get(self.url, {"q": term}), {item.pk})
        CatalogItem.objects.create(
            organization=self.a,
            sku="DISTRACTOR",
            description="100x partA1 OReilly C:parts",
        )
        self.assert_ids(self.client.get(self.url, {"q": "%' OR 1=1 --"}), set())
        self.assert_ids(
            self.client.get(self.url, {"q": "%"}),
            {CatalogItem.objects.get(sku="LITERAL-0").pk},
        )
        self.assert_ids(
            self.client.get(self.url, {"q": "_"}),
            {CatalogItem.objects.get(sku="LITERAL-1").pk},
        )

    def test_unicode_matches_installed_postgresql_comparison(self):
        item = CatalogItem.objects.create(
            organization=self.a, sku="ÉCROU-東京", description="Pièce métallique"
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT UPPER(%s) LIKE UPPER(%s)", [item.sku, "%écrou%"])
            expected_match = cursor.fetchone()[0]
        self.assert_ids(
            self.client.get(self.url, {"q": "écrou"}),
            {item.pk} if expected_match else set(),
        )
        self.assert_ids(self.client.get(self.url, {"q": "東京"}), {item.pk})

    def test_status_filters_and_omission_include_inactive_rows(self):
        archived = CatalogItem.objects.create(
            organization=self.a, sku="ARCHIVED", is_active=False
        )
        self.assert_ids(self.client.get(self.url), {self.item.pk, archived.pk})
        self.assert_ids(
            self.client.get(self.url, {"is_active": "true"}), {self.item.pk}
        )
        self.assert_ids(
            self.client.get(self.url, {"is_active": "false"}), {archived.pk}
        )

    def test_combined_filters_count_order_page_size_and_links(self):
        CatalogItem.objects.bulk_create(
            [
                CatalogItem(
                    organization=self.a,
                    sku=f"FILTER-{i:03}",
                    description="page washer",
                    is_active=True,
                )
                for i in range(55)
            ]
            + [
                CatalogItem(
                    organization=self.a,
                    sku="FILTER-INACTIVE",
                    description="page washer",
                    is_active=False,
                )
            ]
        )
        CatalogItem.objects.bulk_create(
            [
                CatalogItem(
                    organization=self.b, sku=f"FILTER-{i:03}", description="page washer"
                )
                for i in range(55)
            ]
        )
        query = {"q": "washer", "is_active": "true"}
        first = self.client.get(self.url, query).json()
        self.assertEqual(first["count"], 55)
        self.assertEqual(len(first["results"]), 50)
        self.assertEqual(
            [row["sku"] for row in first["results"]],
            [f"FILTER-{i:03}" for i in range(50)],
        )
        next_link = urlsplit(first["next"])
        self.assertEqual(next_link.path, self.url)
        self.assertEqual(
            parse_qs(next_link.query),
            {"q": ["washer"], "is_active": ["true"], "page": ["2"]},
        )
        second = self.client.get(next_link.path + "?" + next_link.query).json()
        self.assertEqual(len(second["results"]), 5)
        previous = urlsplit(second["previous"])
        self.assertEqual(previous.path, self.url)
        self.assertEqual(
            parse_qs(previous.query), {"q": ["washer"], "is_active": ["true"]}
        )
        self.assertTrue(
            all(
                row["organization_id"] == str(self.a.pk)
                for row in first["results"] + second["results"]
            )
        )
        self.assert_clean()

    def test_no_match_has_exact_empty_shape_and_invalid_pages_stay_404(self):
        response = self.client.get(self.url, {"q": "missing-term"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"count": 0, "next": None, "previous": None, "results": []}
        )
        for page in ("0", "", "last", "-1", "2"):
            self.assertEqual(
                self.client.get(
                    self.url, {"q": "missing-term", "page": page}
                ).status_code,
                404,
            )
        self.assert_clean()

    def test_invalid_search_status_unknown_and_repeated_parameters(self):
        queries = (
            "q=",
            "q=%20%20",
            "q=" + "a" * 201,
            "q=%00",
            "q=a&q=b",
            "is_active=",
            "is_active=True",
            "is_active=1",
            "is_active=false&is_active=false",
            "page=1&page=2",
            "page_size=100",
            "ordering=-sku",
            "organization_id=x",
            "sku=x",
            "search=x",
        )
        for query in queries:
            with self.subTest(query=query):
                self.assertEqual(
                    self.client.get(self.url + "?" + query).status_code, 400
                )
                self.assert_clean()
        self.assertEqual(self.client.get(self.url, {"q": "é" * 200}).status_code, 200)

    def test_exact_lookup_trims_like_creation_and_preserves_case_and_identity(self):
        response = self.client.get(self.lookup, {"sku": "  " + self.item.sku + "  "})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), PUBLIC_FIELDS)
        self.assertEqual(body["id"], str(self.item.pk))
        self.assertEqual(body["organization_id"], str(self.a.pk))
        self.assertEqual(body["sku"], self.item.sku)
        self.assertEqual(
            self.client.get(self.lookup, {"sku": self.item.sku.lower()}).status_code,
            404,
        )
        self.assert_private(response)
        self.assert_clean()

    def test_exact_lookup_inactive_and_same_sku_in_another_workspace(self):
        self.assertEqual(self.update({"is_active": False}).status_code, 200)
        result = self.client.get(self.lookup, {"sku": self.item.sku})
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json()["is_active"])
        other_lookup = reverse(
            "workspaces:catalog:by-sku", kwargs={"workspace_id": self.b.pk}
        )
        self.assertEqual(
            self.client.get(other_lookup, {"sku": self.item.sku}).json()["id"],
            str(self.other.pk),
        )
        only_b = CatalogItem.objects.create(organization=self.b, sku="PRIVATE-ONLY-B")
        missing = self.client.get(self.lookup, {"sku": only_b.sku})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json(), {"detail": "Not found."})

    def test_exact_lookup_has_no_invented_model_length_cap(self):
        response = self.post({"sku": "L" * 5000})
        self.assertEqual(response.status_code, 201)
        found = self.client.get(self.lookup, {"sku": "L" * 5000})
        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.json()["id"], response.json()["id"])

    def test_exact_query_validation_is_separate_and_strict(self):
        for query in (
            "",
            "sku=",
            "sku=%20",
            "sku=%00",
            "sku=x&sku=x",
            "sku=x&page=1",
            "sku=x&q=x",
            "sku=x&is_active=true",
            "organization_id=x",
            "q=x",
        ):
            with self.subTest(query=query):
                self.assertEqual(
                    self.client.get(self.lookup + "?" + query).status_code, 400
                )
                self.assert_clean()

    def test_every_member_role_can_search_and_lookup_without_csrf(self):
        for actor in (self.admin, self.viewer, self.reviewer):
            client, _ = self.login_client(actor)
            client.cookies.pop(settings.CSRF_COOKIE_NAME, None)
            self.assert_ids(client.get(self.url, {"q": "Original"}), {self.item.pk})
            self.assertEqual(
                client.get(self.lookup, {"sku": self.item.sku}).status_code, 200
            )

    def test_anonymous_expired_and_inactive_sessions_deny_before_query_errors(self):
        anonymous = APIClient(enforce_csrf_checks=True)
        for path in (self.url + "?q=", self.lookup):
            self.assertEqual(anonymous.get(path).status_code, 403)
        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.lookup).status_code, 403)
        self.admin.is_active = True
        self.admin.save(update_fields=["is_active"])
        Session.objects.filter(
            session_key=self.client.cookies[settings.SESSION_COOKIE_NAME].value
        ).update(expire_date=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get(self.url, {"q": ""}).status_code, 403)
        self.assert_clean()

    def test_inaccessible_inactive_workspaces_memberships_and_operator_denied(self):
        operator, _ = self.login_client(self.outsider)
        for path in (self.url + "?q=", self.lookup):
            self.assertEqual(operator.get(path).status_code, 403)
        for model, pk in (
            (Membership, self.admin_membership.pk),
            (Organization, self.a.pk),
        ):
            model.objects.filter(pk=pk).update(is_active=False)
            self.assertEqual(self.client.get(self.lookup).status_code, 403)
            self.assertEqual(self.client.get(self.url, {"q": ""}).status_code, 403)
            model.objects.filter(pk=pk).update(is_active=True)
        missing = self.lookup.replace(
            str(self.a.pk), "11111111-1111-4111-8111-111111111111"
        )
        self.assertEqual(self.client.get(missing).status_code, 403)
        self.assert_clean()

    def test_url_scope_and_forged_tenant_inputs(self):
        session = self.client.session
        session[SELECTED_WORKSPACE_KEY] = str(self.b.pk)
        session.save()
        response = self.client.get(
            self.lookup,
            {"sku": self.item.sku},
            HTTP_X_ORGANIZATION_ID=str(self.b.pk),
            HTTP_X_USER_ID=str(self.outsider.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(self.item.pk))
        self.assertEqual(
            self.client.get(
                self.lookup, {"sku": self.item.sku, "organization_id": str(self.b.pk)}
            ).status_code,
            400,
        )

    def test_count_slice_lookup_and_serializer_run_inside_read_only_scope(self):
        catalogue_sql = []

        def observe(execute, sql, params, many, context):
            if "catalog_catalogitem" in sql:
                self.assertTrue(connection.in_atomic_block)
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT current_setting('transaction_read_only'), "
                        "current_setting('orderdesk.organization_id')"
                    )
                    self.assertEqual(cursor.fetchone(), ("on", str(self.a.pk)))
                catalogue_sql.append(sql)
            return execute(sql, params, many, context)

        original = CatalogItemSerializer.to_representation

        def serialize(serializer, item):
            self.assertTrue(connection.in_atomic_block)
            with self.assertNumQueries(0):
                return original(serializer, item)

        with (
            connection.execute_wrapper(observe),
            patch.object(CatalogItemSerializer, "to_representation", serialize),
        ):
            listing = self.client.get(self.url, {"q": "Original"})
            lookup = self.client.get(self.lookup, {"sku": self.item.sku})
        self.assertEqual((listing.status_code, lookup.status_code), (200, 200))
        self.assertEqual(len(catalogue_sql), 3)
        self.assertIn("COUNT", catalogue_sql[0])
        self.assertIn("LIMIT 1", catalogue_sql[2])
        with patch.object(connection, "cursor", side_effect=AssertionError("Late SQL")):
            listing.render()
            lookup.render()
        self.assert_clean()

    def test_serialization_failure_cleanup_and_subsequent_workspace_isolation(self):
        with (
            patch.object(
                CatalogItemSerializer,
                "to_representation",
                side_effect=ValueError("Synthetic read failure"),
            ),
            self.assertRaises(ValueError),
        ):
            self.client.get(self.lookup, {"sku": self.item.sku})
        self.assert_clean()
        lookup_b = reverse(
            "workspaces:catalog:by-sku", kwargs={"workspace_id": self.b.pk}
        )
        self.assertEqual(
            self.client.get(lookup_b, {"sku": self.item.sku}).json()["id"],
            str(self.other.pk),
        )
        self.assert_clean()

    def test_lookup_head_options_methods_and_uuid_patch_route_are_preserved(self):
        response = self.client.head(self.lookup, {"sku": self.item.sku})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        self.assert_private(response)
        self.assertEqual(
            self.client.head(self.lookup, {"sku": "missing"}).status_code, 404
        )
        self.assertEqual(
            set(self.client.options(self.lookup)["Allow"].split(", ")),
            {"GET", "HEAD", "OPTIONS"},
        )
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual(
                getattr(self.client, method)(
                    self.lookup, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf
                ).status_code,
                405,
            )
        self.assertEqual(self.update({"description": "Still works"}).status_code, 200)
        self.assertEqual(self.client.get(self.detail).status_code, 405)
        self.assertEqual(self.post({"sku": "CREATION-PRESERVED"}).status_code, 201)

    def test_read_filters_never_loosen_post_or_patch_query_contracts(self):
        for query in ("q=Original", "is_active=true", "page=1"):
            self.assertEqual(
                self.post({"sku": "REJECTED"}, url=self.url + "?" + query).status_code,
                400,
            )
            self.assertEqual(
                self.update(
                    {"description": "REJECTED"}, url=self.detail + "?" + query
                ).status_code,
                400,
            )
