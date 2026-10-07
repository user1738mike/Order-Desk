"""Distributor-owned catalogue identities; matching and import rules come later."""

import uuid

from django.core.validators import RegexValidator
from django.db import models

from apps.organizations.models import Organization


class CatalogItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="catalog_items"
    )
    sku = models.TextField(
        validators=[RegexValidator(r"\S", "Enter a nonblank stock code.")]
    )
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(sku__regex=r"\S"), name="catalog_sku_not_blank"
            ),
            models.UniqueConstraint(
                fields=["organization", "sku"], name="catalog_org_sku_unique"
            ),
        ]

    def __str__(self) -> str:
        return self.sku

    def clean(self) -> None:
        super().clean()
        # Preserve case and punctuation. Import/API boundaries will call validation;
        # save() and bulk operations do not automatically run Django full_clean().
        if isinstance(self.sku, str):
            self.sku = self.sku.strip()
