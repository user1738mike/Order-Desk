"""Direct-runtime HTTP checks; run only through the guarded local API verifier."""

from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import connection, transaction
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.login_limits import login_bucket_key
from apps.accounts.models import LoginAttemptBucket, User
from apps.catalog.models import CatalogItem
from apps.catalog.tests.runtime_rls import OWNER_ALIAS, RuntimeCatalogRLSChecks
from apps.organizations.access import WORKSPACE_ACCESS_DENIED
from apps.organizations.models import Membership, Organization


class RuntimeCatalogAPIChecks(RuntimeCatalogRLSChecks):
    """Reuse owner fixtures; the command selects just the six API-prefixed checks."""

    password = "runtime-catalog-synthetic-password-42"  # noqa: S105 -- test only

    def setUp(self) -> None:
        super().setUp()
        self.session_keys: set[str] = set()
        self.bucket_keys: set[str] = set()
        token = uuid4().hex[:28]
        self.peer = "fd00:" + ":".join(token[i : i + 4] for i in range(0, 28, 4))
        self.addCleanup(self._cleanup_api_sessions)

    def _cleanup_api_sessions(self) -> None:
        connection.close()
        with transaction.atomic(using=OWNER_ALIAS):
            Session.objects.using(OWNER_ALIAS).filter(
                session_key__in=self.session_keys
            ).delete()
            LoginAttemptBucket.objects.using(OWNER_ALIAS).filter(
                pk__in=self.bucket_keys
            ).delete()

    @staticmethod
    def _items_url(workspace: Organization) -> str:
        return reverse(
            "workspaces:catalog:items", kwargs={"workspace_id": workspace.pk}
        )

    def _login(self, actor: User) -> tuple[APIClient, str]:
        actor.set_password(self.password)
        actor.save(using=OWNER_ALIAS, update_fields=["password"])
        client = APIClient(enforce_csrf_checks=True)
        csrf = client.get(reverse("session_auth:csrf")).json()["csrf_token"]
        self.bucket_keys.update(
            (
                login_bucket_key("email", actor.email),
                login_bucket_key("peer", self.peer),
            )
        )
        response = client.post(
            reverse("session_auth:login"),
            {"email": actor.email, "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
            REMOTE_ADDR=self.peer,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.session_keys.add(client.cookies[settings.SESSION_COOKIE_NAME].value)
        return client, response.json()["csrf_token"]

    def test_runtime_api_unfiltered_selector_still_isolates_count_and_rows(self):
        client, csrf = self._login(self.admin)
        selected = client.put(
            reverse("workspaces:current"),
            {"workspace_id": str(self.b.pk)},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(selected.status_code, 200)
        with patch(
            "apps.catalog.selectors.catalog_items_for_workspace",
            side_effect=lambda **kwargs: CatalogItem.objects.order_by("sku", "id"),
        ):
            response = client.get(self._items_url(self.a))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["count"], 2)
            self.assertEqual(
                {row["id"] for row in response.json()["results"]},
                {str(self.item_a.pk), str(self.archived_a.pk)},
            )
            response = client.get(self._items_url(self.b))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["count"], 1)
            self.assertEqual(response.json()["results"][0]["id"], str(self.item_b.pk))
        self._assert_clean()

    def test_runtime_api_admin_creation_preserves_codes_and_clears_scope(self):
        client, csrf = self._login(self.admin)
        response = client.post(
            self._items_url(self.a),
            {
                "sku": "  000Ab/c.D-1  ",
                "description": "Synthetic part",
                "is_active": False,
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["sku"], "000Ab/c.D-1")
        self.assertFalse(body["is_active"])
        item = CatalogItem.objects.using(OWNER_ALIAS).get(pk=body["id"])
        self.assertEqual(item.organization_id, self.a.pk)
        self.assertEqual(client.get(self._items_url(self.a)).json()["count"], 3)
        self.assertEqual(client.get(self._items_url(self.b)).json()["count"], 1)
        self._assert_clean()

    def test_runtime_api_viewer_reviewer_and_operator_cannot_create(self):
        for actor in (self.viewer, self.reviewer, self.outsider):
            client, csrf = self._login(actor)
            with self.subTest(actor=actor.pk):
                response = client.post(
                    self._items_url(self.a),
                    {"sku": "FORBIDDEN"},
                    format="json",
                    HTTP_X_CSRFTOKEN=csrf,
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
                if actor != self.outsider:
                    response = client.get(self._items_url(self.a))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["count"], 2)
                    self.assertIn(
                        False, [row["is_active"] for row in response.json()["results"]]
                    )
                self._assert_clean()
        self.assertEqual(
            CatalogItem.objects.using(OWNER_ALIAS).filter(organization=self.a).count(),
            2,
        )

    def test_runtime_api_denies_foreign_revoked_and_inactive_access(self):
        client, _ = self._login(self.viewer)
        response = client.get(self._items_url(self.b))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": WORKSPACE_ACCESS_DENIED})
        with transaction.atomic(using=OWNER_ALIAS):
            Organization.objects.using(OWNER_ALIAS).select_for_update().get(
                pk=self.a.pk
            )
            Membership.objects.using(OWNER_ALIAS).filter(
                organization=self.a, user=self.viewer
            ).update(is_active=False)
        self.assertEqual(client.get(self._items_url(self.a)).status_code, 403)
        client, _ = self._login(self.admin)
        Organization.objects.using(OWNER_ALIAS).filter(pk=self.a.pk).update(
            is_active=False
        )
        self.assertEqual(client.get(self._items_url(self.a)).status_code, 403)
        Organization.objects.using(OWNER_ALIAS).filter(pk=self.a.pk).update(
            is_active=True
        )
        User.objects.using(OWNER_ALIAS).filter(pk=self.admin.pk).update(is_active=False)
        self.assertEqual(client.get(self._items_url(self.a)).status_code, 403)
        self._assert_clean()

    def test_runtime_api_duplicates_invalid_fields_and_csrf_create_no_rows(self):
        client, csrf = self._login(self.admin)
        url = self._items_url(self.a)
        for payload in (
            {"sku": "PART-001"},
            {"sku": "ARCH-001"},
            {"sku": "NEW", "organization_id": str(self.b.pk)},
            {"sku": 1},
        ):
            with self.subTest(payload=payload):
                response = client.post(
                    url, payload, format="json", HTTP_X_CSRFTOKEN=csrf
                )
                self.assertEqual(response.status_code, 400)
        self.assertEqual(
            client.post(url, {"sku": "NO-CSRF"}, format="json").status_code, 403
        )
        self.assertEqual(
            CatalogItem.objects.using(OWNER_ALIAS).filter(organization=self.a).count(),
            2,
        )
        self._assert_clean()

    def test_runtime_api_pagination_is_bounded_and_strict(self):
        CatalogItem.objects.using(OWNER_ALIAS).bulk_create(
            [CatalogItem(organization=self.a, sku=f"EXTRA-{i:03d}") for i in range(51)]
        )
        client, _ = self._login(self.admin)
        url = self._items_url(self.a)
        first = client.get(url)
        second = client.get(url, {"page": 2})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["count"], 53)
        self.assertEqual(len(first.json()["results"]), 50)
        self.assertEqual(len(second.json()["results"]), 3)
        self.assertIsNotNone(first.json()["next"])
        self.assertIsNone(second.json()["next"])
        rows = first.json()["results"] + second.json()["results"]
        self.assertEqual(
            [row["sku"] for row in rows], sorted(row["sku"] for row in rows)
        )
        self.assertNotIn(str(self.item_b.pk), {row["id"] for row in rows})
        for query, expected in (
            ("page_size=5000", 400),
            ("page=1&page=2", 400),
            ("page=0", 404),
            ("page=3", 404),
        ):
            with self.subTest(query=query):
                self.assertEqual(client.get(url + "?" + query).status_code, expected)
        self._assert_clean()
