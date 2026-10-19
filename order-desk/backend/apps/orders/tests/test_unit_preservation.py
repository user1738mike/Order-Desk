"""Missing units remain unknown; explicit units and decimals stay exact."""

from decimal import Decimal

from django.test import TransactionTestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.orders.models import PurchaseOrder, PurchaseOrderLine
from apps.orders.services import add_order_line
from apps.organizations.services import create_organization


class OrderLineUnitPreservationTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="unit-preservation@example.test")
        self.organization = create_organization(actor=self.user, name="Synthetic units")
        self.order = PurchaseOrder.objects.create(
            organization=self.organization,
            created_by=self.user,
            customer_name="Synthetic buyer",
            purchase_order_number="UNITS-1",
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.url = f"/api/v1/workspaces/{self.organization.pk}/orders/{self.order.pk}/"

    def post(self, data):
        return self.client.post(
            self.url + "lines/", data, format="json", HTTP_X_CSRFTOKEN=self.token
        )

    def test_api_omitted_unit_is_unknown_on_write_and_reload(self):
        response = self.post(
            {"line_number": 1, "sku": "0001.Mixed-Case", "quantity": "1.2345"}
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["unit"], "")
        row = self.client.get(self.url).json()["lines"][0]
        self.assertEqual(
            (row["sku"], row["quantity"], row["unit"]),
            ("0001.Mixed-Case", "1.2345", ""),
        )

    def test_service_omitted_unit_is_unknown_and_explicit_unit_is_preserved(self):
        for position, values, expected in ((1, {}, ""), (2, {"unit": "BOX"}, "BOX")):
            with self.subTest(position=position):
                row = add_order_line(
                    actor=self.user,
                    organization_id=self.organization.pk,
                    order_id=self.order.pk,
                    line_number=position,
                    sku="0001.Mixed-Case",
                    quantity=Decimal("1.2345"),
                    **values,
                )
                self.assertEqual(row.unit, expected)

    def test_explicit_unit_is_preserved_and_quantity_is_required(self):
        response = self.post(
            {
                "line_number": 1,
                "sku": "0001.Mixed-Case",
                "quantity": "1.2345",
                "unit": "BOX",
            }
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["unit"], "BOX")
        rejected = self.post({"line_number": 2, "sku": "0002", "unit": "ea"})
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("quantity", rejected.json())
        self.assertEqual(PurchaseOrderLine.objects.filter(order=self.order).count(), 1)
