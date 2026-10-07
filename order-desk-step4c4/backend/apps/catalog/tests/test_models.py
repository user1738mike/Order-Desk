from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.organizations.services import create_organization


class CatalogItemModelTests(TestCase):
    """Model/constraint checks run as the maintenance owner, not as proof of RLS."""

    @classmethod
    def setUpTestData(cls) -> None:
        actor = User.objects.create_user(email="catalog-owner@example.test")
        cls.organization = create_organization(actor=actor, name="Distributor A")
        cls.other_organization = create_organization(actor=actor, name="Distributor B")

    def test_defaults_and_timestamps(self) -> None:
        item = CatalogItem.objects.create(
            organization=self.organization, sku="PART-001"
        )
        self.assertIsInstance(item.pk, UUID)
        self.assertEqual(item.description, "")
        self.assertTrue(item.is_active)
        self.assertIsNotNone(item.created_at.utcoffset())
        self.assertIsNotNone(item.updated_at.utcoffset())

    def test_validation_trims_edges_and_preserves_case_and_punctuation(self) -> None:
        item = CatalogItem(organization=self.organization, sku=" \tAbC/7-X \n")
        item.full_clean()
        self.assertEqual(item.sku, "AbC/7-X")

    def test_validation_rejects_blank_or_missing_sku(self) -> None:
        for sku in ("", "   ", "\t\n", None):
            with self.subTest(sku=sku), self.assertRaises(ValidationError):
                CatalogItem(organization=self.organization, sku=sku).full_clean()

    def test_database_rejects_blank_sku_when_validation_is_bypassed(self) -> None:
        for sku in ("", "   ", "\t\n"):
            with self.subTest(sku=sku), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    CatalogItem.objects.create(organization=self.organization, sku=sku)

    def test_database_requires_organization(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            CatalogItem.objects.create(sku="ORPHAN")

    def test_same_stock_code_is_valid_across_distributors(self) -> None:
        first = CatalogItem.objects.create(organization=self.organization, sku="SAME")
        second = CatalogItem.objects.create(
            organization=self.other_organization, sku="SAME"
        )
        self.assertNotEqual(first.pk, second.pk)

    def test_duplicate_within_distributor_is_rejected(self) -> None:
        CatalogItem.objects.create(organization=self.organization, sku="SAME")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CatalogItem.objects.create(organization=self.organization, sku="SAME")

    def test_inactive_item_still_reserves_its_stock_code(self) -> None:
        CatalogItem.objects.create(
            organization=self.organization, sku="SAME", is_active=False
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            CatalogItem.objects.create(organization=self.organization, sku="SAME")

    def test_full_clean_detects_duplicate_after_trimming(self) -> None:
        CatalogItem.objects.create(organization=self.organization, sku="SAME")
        with self.assertRaises(ValidationError):
            CatalogItem(organization=self.organization, sku=" SAME ").full_clean()

    def test_case_is_not_automatically_folded(self) -> None:
        CatalogItem.objects.create(organization=self.organization, sku="ABC")
        CatalogItem.objects.create(organization=self.organization, sku="abc")
        self.assertEqual(
            CatalogItem.objects.filter(organization=self.organization).count(), 2
        )

    def test_organization_deletion_is_protected(self) -> None:
        # Avoid the membership FK being the reason for this assertion.
        self.organization.memberships.all().delete()
        CatalogItem.objects.create(organization=self.organization, sku="PROTECTED")
        with self.assertRaises(ProtectedError) as error:
            self.organization.delete()
        self.assertTrue(
            any(
                isinstance(item, CatalogItem)
                for item in error.exception.protected_objects
            )
        )

    def test_deactivation_retains_identity_and_history(self) -> None:
        item = CatalogItem.objects.create(organization=self.organization, sku="KEEP")
        item.is_active = False
        item.save(update_fields=["is_active", "updated_at"])
        item.refresh_from_db()
        self.assertFalse(item.is_active)
        self.assertEqual(item.sku, "KEEP")
