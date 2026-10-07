"""The nonempty, immutable-SKU partial-update input contract."""

from django.test import SimpleTestCase

from apps.catalog.models import CatalogItem
from apps.catalog.serializers import CatalogItemUpdateSerializer


class CatalogUpdateContractTests(SimpleTestCase):
    def test_partial_fields_have_no_defaults(self):
        for data in ({"description": "changed"}, {"is_active": False}):
            serializer = CatalogItemUpdateSerializer(data=data)
            self.assertTrue(serializer.is_valid(), serializer.errors)
            self.assertEqual(serializer.validated_data, data)

    def test_both_fields_and_blank_description_are_allowed(self):
        serializer = CatalogItemUpdateSerializer(
            data={"description": "", "is_active": True}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data, {"description": "", "is_active": True}
        )

    def test_description_preserves_whitespace_and_actual_unbounded_length(self):
        self.assertIsNone(CatalogItem._meta.get_field("description").max_length)
        value = " \t" + "é" * 6000 + "\n "
        serializer = CatalogItemUpdateSerializer(data={"description": value})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["description"], value)

    def test_description_requires_text(self):
        for value in (None, 1, False, [], {}):
            with self.subTest(value=value):
                serializer = CatalogItemUpdateSerializer(data={"description": value})
                self.assertFalse(serializer.is_valid())
                self.assertIn("description", serializer.errors)

    def test_activity_requires_actual_boolean(self):
        for value in (None, 0, 1, "true", "false", [], {}):
            with self.subTest(value=value):
                serializer = CatalogItemUpdateSerializer(data={"is_active": value})
                self.assertFalse(serializer.is_valid())
                self.assertIn("is_active", serializer.errors)

    def test_unknown_and_immutable_fields_are_rejected(self):
        for key in (
            "sku",
            "id",
            "organization",
            "organization_id",
            "user_id",
            "created_at",
            "updated_at",
            "unexpected",
        ):
            with self.subTest(key=key):
                serializer = CatalogItemUpdateSerializer(
                    data={"description": "valid", key: "forged"}
                )
                self.assertFalse(serializer.is_valid())
                self.assertEqual(serializer.errors[key], ["Unknown field."])

    def test_empty_object_and_nonobjects_are_rejected(self):
        for data in ({}, [], None, "text", False, 0):
            with self.subTest(data=data):
                serializer = CatalogItemUpdateSerializer(data=data)
                self.assertFalse(serializer.is_valid())
                self.assertIn("non_field_errors", serializer.errors)

    def test_nonstring_keys_are_rejected_for_direct_service_input(self):
        serializer = CatalogItemUpdateSerializer(data={1: "value"})
        self.assertFalse(serializer.is_valid())
        self.assertEqual(
            serializer.errors, {"non_field_errors": ["Object keys must be strings."]}
        )
