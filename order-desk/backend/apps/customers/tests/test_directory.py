"""Real PostgreSQL customer identity, authorization and immutable approval behavior."""

from django.db import IntegrityError, transaction
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.customers.models import CustomerAccount, CustomerAlias, CustomerLocation
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization


class CustomerDirectoryTests(TransactionTestCase):
    def setUp(self):
        self.actor = User.objects.create_user(email="customer-directory@example.test")
        self.org = create_organization(
            actor=self.actor, name="Synthetic reference directory"
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.actor)
        self.csrf = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.base = f"/api/v1/workspaces/{self.org.pk}/customers/"

    def post(self, url, data, revision=None):
        headers = {"HTTP_IF_MATCH": '"' + revision + '"'} if revision else {}
        return self.client.post(
            url, data, format="json", HTTP_X_CSRFTOKEN=self.csrf, **headers
        )

    def patch(self, url, data):
        revision = self.client.get(url).json()["revision"]
        return self.client.patch(
            url,
            data,
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IF_MATCH='"' + revision + '"',
        )

    def account(self, code="00042", name="Ambiguous buyer"):
        response = self.post(
            self.base, {"code": code, "display_name": name, "destination_id": "000009"}
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def test_stable_codes_preserve_zeros_and_names_do_not_resolve_identity(self):
        a = self.account()
        self.account(code="00043")
        self.assertEqual(a["code"], "00042")
        self.assertEqual(a["destination_id"], "000009")
        results = self.client.get(self.base, {"q": "Ambiguous"}).json()
        self.assertEqual(results["count"], 2)
        resolved = self.client.get(
            self.base + "resolve/", {"identifier": "Ambiguous buyer"}
        ).json()
        self.assertEqual(resolved["matches"], [])
        exact = self.client.get(self.base + "resolve/", {"identifier": "00042"}).json()
        self.assertEqual(exact["matches"][0]["account"]["id"], a["id"])
        self.assertTrue(exact["requires_confirmation"])

    def test_approved_alias_provenance_collision_retirement_and_explicit_replacement(
        self,
    ):
        a, b = self.account(), self.account("00043")
        path = self.base + a["id"] + "/aliases/"
        alias = self.post(
            path,
            {
                "value": "Buyer-PO-Name",
                "provenance": "Synthetic independently approved mapping",
            },
        )
        self.assertEqual(alias.status_code, 201, alias.content)
        record = alias.json()
        self.assertEqual(record["approved_by_id"], str(self.actor.pk))
        other = self.base + b["id"] + "/aliases/"
        self.assertEqual(
            self.post(
                other, {"value": "Buyer-PO-Name", "provenance": "Other"}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.post(other, {"value": "00042", "provenance": "Collision"}).status_code,
            409,
        )
        match = self.client.get(
            self.base + "resolve/", {"identifier": "Buyer-PO-Name"}
        ).json()["matches"][0]
        self.assertEqual(match["evidence"]["kind"], "approved_exact_alias")
        self.assertEqual(
            self.post(
                path + record["id"] + "/retire/",
                {"retirement_reason": "Incorrect source mapping"},
                revision=record["revision"],
            ).status_code,
            200,
        )
        replacement = self.post(
            other,
            {"value": "Buyer-PO-Name", "provenance": "Explicit corrected approval"},
        )
        self.assertEqual(replacement.status_code, 201, replacement.content)
        self.assertEqual(CustomerAlias.objects.count(), 2)
        original = CustomerAlias.objects.get(pk=record["id"])
        self.assertFalse(original.is_active)
        self.assertEqual(
            original.provenance, "Synthetic independently approved mapping"
        )

    def test_multiple_sites_are_scoped_and_inactive_accounts_do_not_resolve(self):
        account = self.account()
        path = self.base + account["id"] + "/locations/"
        for code in ("SITE01", "SITE02"):
            response = self.post(
                path,
                {
                    "code": code,
                    "display_name": "Synthetic destination",
                    "destination_id": "DEST-" + code,
                },
            )
            self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.client.get(path).json()["count"], 2)
        self.assertEqual(
            self.patch(
                self.base + account["id"] + "/", {"is_active": False}
            ).status_code,
            200,
        )
        self.assertEqual(self.client.get(self.base).json()["count"], 0)
        self.assertEqual(
            self.client.get(self.base, {"active": "false"}).json()["count"], 1
        )
        self.assertEqual(
            self.client.get(
                self.base + "resolve/", {"identifier": account["code"]}
            ).json()["matches"],
            [],
        )
        self.assertEqual(
            self.post(path, {"code": "SITE03", "display_name": "Inactive"}).status_code,
            400,
        )

    def test_viewer_reviewer_revocation_csrf_and_foreign_identifiers(self):
        account = self.account()
        for role in (MembershipRole.REVIEWER, MembershipRole.VIEWER):
            Membership.objects.filter(organization=self.org, user=self.actor).update(
                role=role
            )
            self.assertEqual(self.client.get(self.base).status_code, 200)
            self.assertEqual(
                self.post(
                    self.base, {"code": "NEW", "display_name": "Denied"}
                ).status_code,
                403,
            )
        Membership.objects.filter(organization=self.org, user=self.actor).update(
            is_active=False
        )
        self.assertEqual(
            self.client.get(self.base + account["id"] + "/").status_code, 403
        )
        Membership.objects.filter(organization=self.org, user=self.actor).update(
            is_active=True, role=MembershipRole.ADMIN
        )
        foreign = create_organization(actor=self.actor, name="Foreign directory")
        url = self.base.replace(str(self.org.pk), str(foreign.pk)) + account["id"] + "/"
        self.assertEqual(self.client.get(url).status_code, 404)
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.actor)
        self.assertEqual(
            client.post(
                self.base, {"code": "A", "display_name": "Denied"}, format="json"
            ).status_code,
            403,
        )

    def test_database_identity_and_tenant_relationship_guards(self):
        account = self.account()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustomerAccount.objects.filter(pk=account["id"]).update(code="Changed")
        other = create_organization(actor=self.actor, name="Foreign account")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustomerLocation.objects.create(
                organization_id=other.pk,
                customer_id=account["id"],
                code="CROSS",
                display_name="Denied",
                created_by_id=self.actor.pk,
                updated_by_id=self.actor.pk,
            )

    def test_invalid_import_style_ids_unknown_fields_and_repeated_queries_fail(self):
        for body in (
            {"code": 42, "display_name": "Numeric identifiers rejected"},
            {"code": " 00042", "display_name": "Whitespace"},
            {"code": "OK", "display_name": "", "organization_id": str(self.org.pk)},
        ):
            response = self.post(self.base, body)
            # DRF CharField normally coerces numbers: explicit code validation
            # below must preserve the identifier contract rather than invent zeros.
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.client.get(self.base + "?q=a&q=b").status_code, 400)
        self.assertEqual(self.client.get(self.base + "?active=maybe").status_code, 400)
