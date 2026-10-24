"""Native PostgreSQL reference contracts; runtime isolation is a separate gate."""

from uuid import uuid4

from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.customers.models import CustomerAccount
from apps.organizations.models import Membership, MembershipRole
from apps.organizations.services import create_organization
from apps.product_units.models import (
    ControlledUnit,
    ProductUnitPolicy,
    UnitReferenceReceipt,
)


class ProductReferenceTests(TransactionTestCase):
    def setUp(self):
        self.actor = User.objects.create_user(email="units@example.test")
        self.org = create_organization(
            actor=self.actor, name="Synthetic unit references"
        )
        self.product = CatalogItem.objects.create(
            organization=self.org, sku="000123", description="Synthetic item"
        )
        self.customer = CustomerAccount.objects.create(
            organization=self.org,
            created_by=self.actor,
            updated_by=self.actor,
            code="00042",
            display_name="Synthetic buyer",
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.actor)
        self.csrf = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.base = f"/api/v1/workspaces/{self.org.pk}/product-units/"

    def write(self, path, data, key=None, revision=None, method="post"):
        return getattr(self.client, method)(
            self.base + path,
            data,
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_IDEMPOTENCY_KEY=str(key or uuid4()),
            **({"HTTP_IF_MATCH": '"' + revision + '"'} if revision else {}),
        )

    def unit(self, code):
        response = self.write("units/", {"code": code, "display_name": code})
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def policy_data(self):
        each, case = self.unit("ea"), self.unit("case")
        return {
            "catalogue_item_id": str(self.product.pk),
            "requested_token": "EACH",
            "requested_unit_id": each["id"],
            "selling_unit_id": case["id"],
            "selling_numerator": "1",
            "selling_denominator": "12",
            "selling_scale": 3,
            "selling_max_integer_digits": 9,
            "provenance": "Synthetic approved pack of twelve",
        }

    def test_exact_factors_durable_replay_and_immutable_policy_retirement(self):
        data = self.policy_data()
        key = uuid4()
        result = self.write("policies/", data, key=key)
        self.assertEqual(result.status_code, 201, result.content)
        policy = result.json()
        self.assertEqual(policy["selling_denominator"], "12.000000000000")
        self.assertEqual(
            self.write("policies/", data, key=key).json()["id"], policy["id"]
        )
        changed = {**data, "selling_denominator": "10"}
        self.assertEqual(self.write("policies/", changed, key=key).status_code, 409)
        row = ProductUnitPolicy.objects.get(pk=policy["id"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductUnitPolicy.objects.filter(pk=row.pk).update(selling_denominator=10)
        retired = self.write(
            "policies/" + policy["id"] + "/",
            {"retirement_reason": "Synthetic correction"},
            revision=policy["revision"],
        )
        self.assertEqual(retired.status_code, 200, retired.content)
        self.assertEqual(self.write("policies/", changed).status_code, 201)
        self.assertEqual(ProductUnitPolicy.objects.count(), 2)
        self.assertEqual(
            self.client.get(self.base + "operations/" + str(key) + "/").json()["id"],
            policy["id"],
        )

    def test_stale_write_then_exact_replay_after_committed_update(self):
        unit = self.unit("000EA")
        path = "units/" + unit["id"] + "/"
        self.assertEqual(
            self.write(path, {"display_name": "Each"}, method="patch").status_code, 428
        )
        key = uuid4()
        args = {"revision": unit["revision"], "key": key, "method": "patch"}
        response = self.write(path, {"display_name": "Each"}, **args)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(
            self.write(path, {"display_name": "Each"}, **args).json()["replayed"]
        )
        self.assertEqual(
            self.write(
                path,
                {"display_name": "Stale"},
                revision=unit["revision"],
                method="patch",
            ).status_code,
            412,
        )
        self.assertEqual(
            self.write(
                path,
                {"code": "MUTATE"},
                revision=response.json()["revision"],
                method="patch",
            ).status_code,
            400,
        )
        self.assertEqual(ControlledUnit.objects.get(pk=unit["id"]).code, "000EA")

    def test_numeric_input_factors_precision_and_partial_destination_are_rejected(self):
        data = self.policy_data()
        for value in (
            1.5,
            1,
            "NaN",
            "Infinity",
            "1e3",
            " 1",
            "0",
            "-1",
            "１",
            "1000000000000",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    self.write(
                        "policies/", {**data, "selling_numerator": value}
                    ).status_code,
                    400,
                )
        for fields in (
            {"selling_scale": True},
            {"selling_scale": 10},
            {"selling_scale": "3"},
            {"destination_numerator": "1"},
        ):
            self.assertEqual(
                self.write("policies/", {**data, **fields}).status_code, 400
            )
        self.assertEqual(
            self.write(
                "units/", {"code": 1, "display_name": "No numeric identifier"}
            ).status_code,
            400,
        )
        self.assertFalse(ProductUnitPolicy.objects.exists())

    def test_alias_customer_scope_collision_retirement_and_no_automatic_learning(self):
        data = {
            "customer_id": str(self.customer.pk),
            "catalogue_item_id": str(self.product.pk),
            "value": "000PO-PRODUCT",
            "provenance": "Explicit synthetic customer approval",
        }
        result = self.write("aliases/", data)
        self.assertEqual(result.status_code, 201, result.content)
        other = CatalogItem.objects.create(organization=self.org, sku="OTHER")
        self.assertEqual(
            self.write(
                "aliases/", {**data, "catalogue_item_id": str(other.pk)}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.write(
                "aliases/",
                {**data, "catalogue_item_id": str(other.pk), "value": "000123"},
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.get(
                self.base + "aliases/", {"customer_id": str(uuid4())}
            ).json()["count"],
            0,
        )
        alias = result.json()
        self.assertEqual(
            self.write(
                "aliases/" + alias["id"] + "/",
                {"retirement_reason": "Customer withdrew mapping"},
                revision=alias["revision"],
            ).status_code,
            200,
        )
        self.assertEqual(
            self.write(
                "aliases/", {**data, "catalogue_item_id": str(other.pk)}
            ).status_code,
            201,
        )

    def test_fresh_role_csrf_revocation_foreign_parent_and_bounded_queries(self):
        data = self.policy_data()
        second = User.objects.create_user(email="foreign-units@example.test")
        foreign = create_organization(actor=second, name="Foreign synthetic workspace")
        unit = ControlledUnit.objects.create(
            organization=foreign,
            code="FOREIGN",
            display_name="Foreign",
            created_by=second,
            updated_by=second,
        )
        self.assertEqual(
            self.write(
                "policies/", {**data, "selling_unit_id": str(unit.pk)}
            ).status_code,
            404,
        )
        for role in (
            MembershipRole.REVIEWER,
            MembershipRole.PROCESSOR,
            MembershipRole.VIEWER,
        ):
            Membership.objects.filter(organization=self.org, user=self.actor).update(
                role=role
            )
            self.assertEqual(self.client.get(self.base + "units/").status_code, 200)
            self.assertEqual(self.write("policies/", data).status_code, 403)
        self.assertEqual(
            self.client.post(self.base + "units/", {}, format="json").status_code, 403
        )
        self.assertEqual(self.client.get(self.base + "units/?q=a&q=b").status_code, 400)
        Membership.objects.filter(organization=self.org, user=self.actor).update(
            is_active=False
        )
        self.assertEqual(self.client.get(self.base + "units/").status_code, 403)

    def test_native_schema_is_forced_rls_and_pending_decision_writes_are_denied(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE relname LIKE 'product_units_%%' AND relkind='r'"
            )
            rows = cursor.fetchall()
            self.assertEqual(len(rows), 6)
            self.assertTrue(all(enabled and forced for _, enabled, forced in rows))
            cursor.execute(
                "SELECT has_table_privilege('orderdesk_app',"
                "'public.product_units_draftlineunitdecision','INSERT'),"
                "has_table_privilege('orderdesk_app',"
                "'public.product_units_orderlineunitsnapshot','INSERT')"
            )
            self.assertEqual(cursor.fetchone(), (False, False))
        self.assertFalse(UnitReferenceReceipt.objects.exists())
