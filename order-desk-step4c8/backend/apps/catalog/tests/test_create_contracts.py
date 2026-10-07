"""Strict creation payload contracts without database access."""

from uuid import uuid4

from django.test import SimpleTestCase

from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemCreateSerializer


class CatalogCreateContractTests(SimpleTestCase):
    def valid_data(self, data: object) -> dict:
        serializer = CatalogItemCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return serializer.validated_data

    def test_stock_code_is_required(self):
        serializer = CatalogItemCreateSerializer(data={})
        self.assertFalse(serializer.is_valid())
        self.assertEqual(set(serializer.errors), {"sku"})
        self.assertEqual(serializer.errors["sku"][0].code, "required")

    def test_omitted_optional_fields_use_actual_model_defaults(self):
        data = self.valid_data({"sku": "PART-001"})
        self.assertEqual(
            data,
            {
                "sku": "PART-001",
                "description": CatalogItem._meta.get_field("description").get_default(),
                "is_active": CatalogItem._meta.get_field("is_active").get_default(),
            },
        )

    def test_payload_must_be_an_object(self):
        for data in (None, True, 1, 1.5, "PART-001", [], ["PART-001"]):
            with self.subTest(data=data):
                serializer = CatalogItemCreateSerializer(data=data)
                self.assertFalse(serializer.is_valid())
                self.assertEqual(set(serializer.errors), {"non_field_errors"})

    def test_stock_code_requires_actual_text_without_numeric_or_boolean_coercion(self):
        for sku in (None, True, False, 1, 1.5, [], {"stock": "PART-001"}):
            with self.subTest(sku=sku):
                serializer = CatalogItemCreateSerializer(data={"sku": sku})
                self.assertFalse(serializer.is_valid())
                self.assertEqual(set(serializer.errors), {"sku"})

    def test_empty_and_unicode_whitespace_only_stock_codes_are_rejected(self):
        for sku in ("", " ", "\t\r\n", "\u2003\u00a0"):
            with self.subTest(sku=sku):
                serializer = CatalogItemCreateSerializer(data={"sku": sku})
                self.assertFalse(serializer.is_valid())
                self.assertEqual(serializer.errors["sku"][0].code, "blank")

    def test_stock_code_trims_only_edges_preserving_identity_text(self):
        data = self.valid_data({"sku": " \t000Ab/P-1.x internal SPACE\n"})
        self.assertEqual(data["sku"], "000Ab/P-1.x internal SPACE")

    def test_description_preserves_whitespace_and_accepts_empty_text(self):
        for description in ("", "  Synthetic part\n\t "):
            with self.subTest(description=description):
                data = self.valid_data({"sku": "PART-001", "description": description})
                self.assertEqual(data["description"], description)

    def test_description_requires_actual_text_when_supplied(self):
        for description in (None, True, False, 1, 1.5, [], {}):
            with self.subTest(description=description):
                serializer = CatalogItemCreateSerializer(
                    data={"sku": "PART-001", "description": description}
                )
                self.assertFalse(serializer.is_valid())
                self.assertEqual(set(serializer.errors), {"description"})

    def test_activity_requires_json_booleans_and_preserves_false(self):
        self.assertFalse(
            self.valid_data({"sku": "PART-001", "is_active": False})["is_active"]
        )
        for is_active in (None, "true", "false", "1", 1, 0, [], {}):
            with self.subTest(is_active=is_active):
                serializer = CatalogItemCreateSerializer(
                    data={"sku": "PART-001", "is_active": is_active}
                )
                self.assertFalse(serializer.is_valid())
                self.assertEqual(set(serializer.errors), {"is_active"})

    def test_unknown_and_protected_fields_are_rejected_instead_of_dropped(self):
        for field in (
            "id",
            "organization",
            "organization_id",
            "user_id",
            "created_at",
            "updated_at",
            "extra",
        ):
            with self.subTest(field=field):
                serializer = CatalogItemCreateSerializer(
                    data={"sku": "PART-001", field: str(uuid4())}
                )
                self.assertFalse(serializer.is_valid())
                self.assertEqual(serializer.errors, {field: ["Unknown field."]})

    def test_unknown_fields_are_reported_before_allowed_field_validation(self):
        serializer = CatalogItemCreateSerializer(
            data={"organization_id": str(uuid4()), "unexpected": True, "sku": None}
        )
        self.assertFalse(serializer.is_valid())
        self.assertEqual(set(serializer.errors), {"organization_id", "unexpected"})

    def test_direct_service_payload_keys_must_be_strings(self):
        serializer = CatalogItemCreateSerializer(data={1: "PART-001", "sku": "OK"})
        self.assertFalse(serializer.is_valid())
        self.assertEqual(
            serializer.errors, {"non_field_errors": ["Object keys must be strings."]}
        )

    def test_text_fields_accept_above_255_characters_as_defined_by_the_model(self):
        self.assertIsNone(CatalogItem._meta.get_field("sku").max_length)
        self.assertIsNone(CatalogItem._meta.get_field("description").max_length)
        data = self.valid_data({"sku": "A" * 1024, "description": "D" * 2048})
        self.assertEqual(len(data["sku"]), 1024)
        self.assertEqual(len(data["description"]), 2048)
