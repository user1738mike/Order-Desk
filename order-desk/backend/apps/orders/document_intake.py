"""Short metadata finalization after bounded private streaming and validation."""

from apps.orders import selectors
from apps.orders.models import OrderDocument
from apps.orders.private_documents import staged_document
from apps.orders.services import _locked_order, _require_editable_order, _require_writer
from apps.organizations.transactions import tenant_scope


def create_private_document(*, actor, organization_id, order_id, upload, materialize):
    with tenant_scope(user=actor, workspace_id=organization_id) as context:
        _require_writer(context)
        order = selectors.private_document_parent(organization_id, order_id)
        _require_editable_order(order)
    # No DB transaction/organization lock while receiving or validating source bytes.
    source = upload() if callable(upload) else upload
    with staged_document(source) as staged:
        with tenant_scope(
            user=actor, workspace_id=organization_id, write=True
        ) as context:
            _require_writer(context)
            order = _locked_order(organization_id=organization_id, order_id=order_id)
            _require_editable_order(order)
            document = OrderDocument(
                organization_id=organization_id,
                order=order,
                uploaded_by=actor,
                original_name=staged["name"],
                content_type=staged["content_type"],
                size_bytes=staged["size"],
                source_sha256=staged["sha256"],
                file=staged["key"],
            )
            document.full_clean()
            document.save()
            result = materialize(document)
            # An acknowledgement failure at COMMIT is ambiguous. Keep source bytes
            # until a leased reconciliation can check committed metadata.
            staged["commit_attempt"] = True
        staged["committed"] = True
        return result
