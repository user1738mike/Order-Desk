"""Approved tenant reference data; names and filenames never establish identity."""

import uuid

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

CODE = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,63}$"


class ReferenceRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class CustomerAccount(ReferenceRecord):
    code = models.CharField(max_length=64, validators=[RegexValidator(CODE)])
    display_name = models.CharField(max_length=255)
    destination_id = models.CharField(max_length=128, blank=True, default="")
    requires_location = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["id", "organization"], name="customer_id_org_unique"
            ),
            models.UniqueConstraint(
                fields=["organization", "code"], name="customer_org_code_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(code__regex=CODE), name="customer_code_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(display_name__regex=r"\S"),
                name="customer_name_nonblank",
            ),
        ]
        ordering = ["code", "id"]

    def __str__(self):
        return self.code


class CustomerLocation(ReferenceRecord):
    customer = models.ForeignKey(
        CustomerAccount, on_delete=models.PROTECT, related_name="locations"
    )
    code = models.CharField(max_length=64, validators=[RegexValidator(CODE)])
    display_name = models.CharField(max_length=255)
    destination_id = models.CharField(max_length=128, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["id", "organization", "customer"],
                name="customer_site_identity_unique",
            ),
            models.UniqueConstraint(
                fields=["organization", "customer", "code"],
                name="customer_site_code_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(code__regex=CODE), name="customer_site_code_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(display_name__regex=r"\S"),
                name="customer_site_name_nonblank",
            ),
        ]
        ordering = ["code", "id"]

    def __str__(self):
        return self.code


class CustomerAlias(ReferenceRecord):
    customer = models.ForeignKey(
        CustomerAccount, on_delete=models.PROTECT, related_name="aliases"
    )
    value = models.CharField(max_length=128)
    provenance = models.CharField(max_length=500)
    is_active = models.BooleanField(default=True)
    retirement_reason = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["id", "organization", "customer"],
                name="customer_alias_identity_unique",
            ),
            models.UniqueConstraint(
                fields=["organization", "value"],
                condition=models.Q(is_active=True),
                name="customer_active_alias_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(value__regex=r"\S"), name="customer_alias_nonblank"
            ),
            models.CheckConstraint(
                condition=models.Q(provenance__regex=r"\S"),
                name="customer_alias_provenance",
            ),
            models.CheckConstraint(
                condition=models.Q(is_active=True, retirement_reason="")
                | (
                    models.Q(is_active=False) & models.Q(retirement_reason__regex=r"\S")
                ),
                name="customer_alias_retirement",
            ),
        ]
        ordering = ["value", "id"]

    def __str__(self):
        return str(self.pk)


class DraftCustomerDecision(models.Model):
    """Append-only confirmations; only explicit retirement metadata can change."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    draft = models.ForeignKey(
        "orders.DraftOrder", on_delete=models.PROTECT, related_name="customer_decisions"
    )
    customer = models.ForeignKey(CustomerAccount, on_delete=models.PROTECT)
    location = models.ForeignKey(
        CustomerLocation, on_delete=models.PROTECT, null=True, blank=True
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="customer_confirmations",
    )
    operation_key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    request = models.JSONField()
    reference_revision = models.CharField(max_length=64)
    snapshot = models.JSONField()
    is_current = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    retired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="retired_customer_confirmations",
    )
    retirement_reason = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["id", "organization", "draft"],
                name="customer_decision_identity",
            ),
            models.UniqueConstraint(
                fields=["organization", "operation_key"],
                name="customer_decision_operation",
            ),
            models.UniqueConstraint(
                fields=["organization", "draft"],
                condition=models.Q(is_current=True),
                name="customer_one_current_decision",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    request_hash__regex=r"^[0-9a-f]{64}$",
                    reference_revision__regex=r"^[0-9a-f]{64}$",
                ),
                name="customer_decision_hashes",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    is_current=True,
                    retired_at__isnull=True,
                    retired_by__isnull=True,
                    retirement_reason="",
                )
                | (
                    models.Q(is_current=False, retired_at__isnull=False)
                    & ~models.Q(retirement_reason="")
                ),
                name="customer_decision_retirement",
            ),
        ]
        ordering = ["-created_at", "id"]

    def __str__(self):
        return str(self.pk)


class OrderCustomerSnapshot(models.Model):
    """Immutable customer/destination data copied from the confirmed decision."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    order = models.OneToOneField(
        "orders.PurchaseOrder",
        on_delete=models.PROTECT,
        related_name="customer_snapshot",
    )
    draft = models.ForeignKey("orders.DraftOrder", on_delete=models.PROTECT)
    decision = models.ForeignKey(DraftCustomerDecision, on_delete=models.PROTECT)
    payload = models.JSONField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="frozen_customer_snapshots",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.pk)


class ReferenceWriteReceipt(models.Model):
    """Atomic repeat-safe reference writes and their original committed responses."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    customer = models.ForeignKey(
        CustomerAccount, on_delete=models.PROTECT, null=True, blank=True
    )
    location = models.ForeignKey(
        CustomerLocation, on_delete=models.PROTECT, null=True, blank=True
    )
    alias = models.ForeignKey(
        CustomerAlias, on_delete=models.PROTECT, null=True, blank=True
    )
    operation_key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    kind = models.CharField(max_length=32)
    source_sha256 = models.CharField(max_length=64, blank=True, default="")
    response = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "operation_key"],
                name="customer_write_operation_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(request_hash__regex=r"^[0-9a-f]{64}$"),
                name="customer_write_hash_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(source_sha256="")
                | models.Q(source_sha256__regex=r"^[0-9a-f]{64}$"),
                name="customer_write_source_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind__in=["account.create", "account.update"],
                        customer__isnull=False,
                        location__isnull=True,
                        alias__isnull=True,
                    )
                    | models.Q(
                        kind__in=["location.create", "location.update"],
                        customer__isnull=False,
                        location__isnull=False,
                        alias__isnull=True,
                    )
                    | models.Q(
                        kind__in=["alias.create", "alias.update"],
                        customer__isnull=False,
                        location__isnull=True,
                        alias__isnull=False,
                    )
                    | models.Q(
                        kind="account.import",
                        customer__isnull=True,
                        location__isnull=True,
                        alias__isnull=True,
                    )
                ),
                name="customer_write_target_valid",
            ),
        ]
        ordering = ["-created_at", "id"]

    def __str__(self):
        return str(self.pk)
