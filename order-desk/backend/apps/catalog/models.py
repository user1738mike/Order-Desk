"""Distributor-owned catalogue identities and durable create-only import receipts."""

import uuid

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Cast
from django.db.models.lookups import Exact, LessThanOrEqual

from apps.organizations.models import Organization

CONTRACT_IDENTIFIER = "catalogue-create-only-csv-v1"
MAX_RECEIPT_PAYLOAD_BYTES = 8 * 1_048_576


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
            models.UniqueConstraint(
                fields=["id", "organization"], name="catalog_id_org_unique"
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


class CatalogImportReceipt(models.Model):
    """An import and its completed response commit in the same transaction."""

    CONTRACT_IDENTIFIER = CONTRACT_IDENTIFIER

    class State(models.TextChoices):
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="catalog_import_receipts"
    )
    initiating_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="catalog_import_receipts",
    )
    idempotency_key = models.UUIDField()
    request_fingerprint = models.CharField(
        max_length=64,
        validators=[RegexValidator(r"^[0-9a-f]{64}$", "Use a SHA-256 fingerprint.")],
    )
    mode = models.CharField(max_length=20, default="create_only")
    contract_identifier = models.CharField(max_length=40, default=CONTRACT_IDENTIFIER)
    state = models.CharField(
        max_length=10, choices=State.choices, default=State.PROCESSING
    )
    response_payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="catalog_import_org_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(mode="create_only"),
                name="catalog_import_create_only_mode",
            ),
            models.CheckConstraint(
                condition=models.Q(contract_identifier=CONTRACT_IDENTIFIER),
                name="catalog_import_contract_identifier",
            ),
            models.CheckConstraint(
                condition=models.Q(request_fingerprint__regex=r"^[0-9a-f]{64}$"),
                name="catalog_import_fingerprint_sha256",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state="processing",
                        response_payload__isnull=True,
                        completed_at__isnull=True,
                    )
                    | models.Q(
                        state="completed",
                        response_payload__isnull=False,
                        completed_at__isnull=False,
                    )
                ),
                name="catalog_import_completion_shape",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(completed_at__isnull=True)
                    | models.Q(completed_at__gte=models.F("created_at"))
                ),
                name="catalog_import_completion_time",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(response_payload__isnull=True)
                    | Exact(
                        models.Func(
                            "response_payload",
                            function="jsonb_typeof",
                            output_field=models.CharField(),
                        ),
                        "object",
                    )
                ),
                name="catalog_import_response_object",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(response_payload__isnull=True)
                    | LessThanOrEqual(
                        models.Func(
                            Cast("response_payload", output_field=models.TextField()),
                            function="octet_length",
                            output_field=models.IntegerField(),
                        ),
                        MAX_RECEIPT_PAYLOAD_BYTES,
                    )
                ),
                name="catalog_import_response_size",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)
