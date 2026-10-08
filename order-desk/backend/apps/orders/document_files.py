"""Framework-independent bounds for source documents passed to order services."""

from collections.abc import Iterator
from contextlib import contextmanager
from tempfile import SpooledTemporaryFile

from django.core.exceptions import ValidationError
from django.core.files import File

MAX_ORDER_DOCUMENT_BYTES = 10 * 1024 * 1024
DOCUMENT_TOO_LARGE = "The purchase-order document exceeds the 10 MiB upload limit."


class OrderDocumentTooLarge(ValidationError):
    """Actual document bytes exceed the accepted local intake bound."""

    def __init__(self):
        super().__init__({"file": [DOCUMENT_TOO_LARGE]})


@contextmanager
def bounded_document_file(upload) -> Iterator[File]:
    """Read actual bytes into a bounded spillable copy, ignoring size metadata."""
    with SpooledTemporaryFile(max_size=64 * 1024, mode="w+b") as stream:
        upload.seek(0)
        received = 0
        while chunk := upload.read(
            min(64 * 1024, MAX_ORDER_DOCUMENT_BYTES + 1 - received)
        ):
            received += len(chunk)
            if received > MAX_ORDER_DOCUMENT_BYTES:
                raise OrderDocumentTooLarge()
            stream.write(chunk)
        stream.seek(0)
        yield File(stream, name=upload.name)
