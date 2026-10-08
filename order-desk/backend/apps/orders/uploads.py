"""Bounded purchase-order document upload transport."""

from django.core.files.uploadhandler import FileUploadHandler
from rest_framework.exceptions import APIException

from apps.orders.document_files import DOCUMENT_TOO_LARGE, MAX_ORDER_DOCUMENT_BYTES


class OrderDocumentUploadTooLarge(APIException):
    status_code = 413
    default_code = "upload_too_large"
    default_detail = {"detail": DOCUMENT_TOO_LARGE}


class OrderDocumentUploadLimitHandler(FileUploadHandler):
    """Count aggregate bytes while forwarding multipart chunks to Django."""

    def __init__(self, request):
        super().__init__(request)
        self.received = 0

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > MAX_ORDER_DOCUMENT_BYTES:
            for handler in self.request.upload_handlers:
                current = getattr(handler, "file", None)
                if current is not None:
                    current.close()
            raise OrderDocumentUploadTooLarge()
        return raw_data

    def file_complete(self, file_size):
        return None
