"""Upload-first sources and one-time, repeat-safe draft linkage."""

import hashlib
import json

from django.core.exceptions import ValidationError
from django.db.models import Count, OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException

from apps.orders import selectors
from apps.orders.models import DocumentExtractionJob, DraftOrder, OrderDocument
from apps.orders.private_documents import staged_document
from apps.orders.revisions import check_revision
from apps.orders.serializers import PrivateDocumentSerializer, StrictInputSerializer
from apps.orders.services import _require_draft_editable, _require_preparer
from apps.organizations.transactions import tenant_scope


class IncomingConflict(APIException):
    status_code = 409
    default_detail = "Request conflicts with the recorded source operation."


class LinkInput(StrictInputSerializer):
    operation_key = serializers.UUIDField()
    draft_id = serializers.UUIDField(required=False)
    expected_revision = serializers.RegexField(r"^[0-9a-f]{64}$", required=False)
    customer_name = serializers.CharField(
        max_length=255, allow_blank=True, required=False, default=""
    )
    customer_reference = serializers.CharField(
        max_length=128, allow_blank=True, required=False, default=""
    )

    def validate(self, attrs):
        if "draft_id" in attrs:
            if not attrs.get("expected_revision"):
                raise serializers.ValidationError(
                    {"expected_revision": "Refresh the selected draft."}
                )
            if attrs["customer_name"] or attrs["customer_reference"]:
                raise serializers.ValidationError(
                    "Linking does not edit customer fields."
                )
        elif "expected_revision" in attrs:
            raise serializers.ValidationError("A revision requires a selected draft.")
        return attrs


class IncomingSerializer(PrivateDocumentSerializer):
    processing_status = serializers.CharField(read_only=True, allow_null=True)
    duplicate_count = serializers.IntegerField(read_only=True, default=0)
    reference_duplicate_count = serializers.IntegerField(read_only=True, default=0)
    customer_name = serializers.CharField(
        source="draft.customer_name", read_only=True, default=""
    )
    customer_reference = serializers.CharField(
        source="draft.customer_reference", read_only=True, default=""
    )

    class Meta(PrivateDocumentSerializer.Meta):
        fields = (
            *PrivateDocumentSerializer.Meta.fields,
            "draft",
            "intake_key",
            "linked_by",
            "linked_at",
            "processing_status",
            "duplicate_count",
            "reference_duplicate_count",
            "customer_name",
            "customer_reference",
        )
        read_only_fields = fields


def inbox(organization_id):
    references = (
        DraftOrder.objects.filter(
            organization_id=organization_id,
            customer_reference=OuterRef("draft__customer_reference"),
        )
        .exclude(customer_reference="")
        .exclude(pk=OuterRef("draft_id"))
        .values("customer_reference")
        .annotate(total=Count("pk"))
        .values("total")
    )
    peers = (
        OrderDocument.objects.filter(
            organization_id=organization_id,
            order__isnull=True,
            source_sha256=OuterRef("source_sha256"),
        )
        .exclude(pk=OuterRef("pk"))
        .values("source_sha256")
        .annotate(total=Count("pk"))
        .values("total")
    )
    jobs = (
        DocumentExtractionJob.objects.filter(
            organization_id=organization_id, document_id=OuterRef("pk")
        )
        .order_by("-created_at")
        .values("status")
    )
    return (
        OrderDocument.objects.filter(
            organization_id=organization_id, order__isnull=True
        )
        .select_related("draft")
        .annotate(
            processing_status=Subquery(jobs[:1]),
            duplicate_count=Subquery(peers[:1]),
            reference_duplicate_count=Subquery(references[:1]),
        )
        .order_by("-uploaded_at", "id")
    )


def receive(*, actor, organization_id, operation_key, upload):
    with tenant_scope(user=actor, workspace_id=organization_id) as context:
        _require_preparer(context)
    with staged_document(upload()) as staged:
        with tenant_scope(
            user=actor, workspace_id=organization_id, write=True
        ) as context:
            _require_preparer(context)
            previous = OrderDocument.objects.filter(
                organization_id=organization_id, intake_key=operation_key
            ).first()
            if previous is not None:
                if (
                    previous.source_sha256,
                    previous.original_name,
                    previous.size_bytes,
                ) != (staged["sha256"], staged["name"], staged["size"]):
                    raise IncomingConflict(
                        "This upload request key already identifies "
                        "different bytes or metadata."
                    )
                return IncomingSerializer(
                    inbox(organization_id).get(pk=previous.pk)
                ).data, False
            document = OrderDocument(
                organization_id=organization_id,
                uploaded_by_id=actor.pk,
                intake_key=operation_key,
                file=staged["key"],
                original_name=staged["name"],
                size_bytes=staged["size"],
                content_type=staged["content_type"],
                source_sha256=staged["sha256"],
            )
            document.full_clean()
            document.save()
            result = IncomingSerializer(inbox(organization_id).get(pk=document.pk)).data
            staged["commit_attempt"] = True
        staged["committed"] = True
        return result, True


def link(*, actor, organization_id, document_id, data):
    with tenant_scope(user=actor, workspace_id=organization_id, write=True) as context:
        _require_preparer(context)
        form = LinkInput(data=data())
        form.is_valid(raise_exception=True)
        values = form.validated_data
        key = values.pop("operation_key")
        digest = hashlib.sha256(
            json.dumps(values, sort_keys=True, default=str).encode()
        ).hexdigest()
        document = selectors.get_private_document(organization_id, None, document_id)
        if document.draft_id is not None:
            if document.link_key != key or document.link_hash != digest:
                raise IncomingConflict(
                    "This source already has a draft. Refresh its recorded link."
                )
            return IncomingSerializer(
                inbox(organization_id).get(pk=document.pk)
            ).data, False
        if "draft_id" in values:
            draft = get_object_or_404(
                DraftOrder.objects.select_for_update().filter(
                    organization_id=organization_id
                ),
                pk=values["draft_id"],
            )
            _require_draft_editable(draft)
            check_revision(draft, values["expected_revision"])
        else:
            draft = DraftOrder(
                organization_id=organization_id,
                initiating_user_id=actor.pk,
                customer_name=values["customer_name"],
                customer_reference=values["customer_reference"],
            )
            draft.full_clean()
            draft.save()
        document.draft = draft
        document.linked_by_id = actor.pk
        document.linked_at = timezone.now()
        document.link_key, document.link_hash = key, digest
        document.full_clean()
        document.save(
            update_fields=["draft", "linked_by", "linked_at", "link_key", "link_hash"]
        )
        return IncomingSerializer(inbox(organization_id).get(pk=document.pk)).data, True


def require_source_editable(organization_id, document):
    from apps.orders.services import _locked_order, _require_editable_order

    if document.order_id is not None:
        _require_editable_order(
            _locked_order(organization_id=organization_id, order_id=document.order_id)
        )
    elif document.draft_id is not None:
        draft = get_object_or_404(
            DraftOrder, organization_id=organization_id, pk=document.draft_id
        )
        if draft.status != DraftOrder.Status.DRAFT:
            raise ValidationError({"draft": "The linked draft is already converted."})
