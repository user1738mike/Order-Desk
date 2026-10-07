"""CSV-only upload bounds, installed before session CSRF can parse multipart."""

from django.core.files.uploadhandler import FileUploadHandler
from rest_framework.exceptions import ValidationError

from apps.catalog.imports import MAX_FILE_BYTES, ImportUploadTooLarge


class CatalogUploadLimitHandler(FileUploadHandler):
    """Bound aggregate file bytes; forward valid chunks to normal Django handlers."""

    def __init__(self, request):
        super().__init__(request)
        self.received = 0

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > MAX_FILE_BYTES:
            # Django closes completed uploads when parsing raises, but an
            # in-progress temporary file belongs to its current upload handler.
            for handler in self.request.upload_handlers:
                current = getattr(handler, "file", None)
                if current is not None:
                    current.close()
            raise ImportUploadTooLarge()
        return raw_data

    def file_complete(self, file_size):
        return None


def catalogue_upload_bytes(request) -> bytes:
    """Validate complete multipart shape and read at most the byte limit + one."""
    if request.query_params:
        raise ValidationError(
            {key: ["Unknown query parameter."] for key in request.query_params}
        )
    # DRF's multipart parser reuses Django's already parsed POST/FILES after CSRF.
    data = request.data
    files = request.FILES
    if set(data) != {"file"} or set(files) != {"file"}:
        raise ValidationError({"file": ["Supply exactly one file and no form fields."]})
    if len(files.getlist("file")) != 1 or len(data.getlist("file")) != 1:
        raise ValidationError({"file": ["Supply exactly one file and no form fields."]})
    upload = files["file"]
    upload.seek(0)
    raw = upload.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ImportUploadTooLarge()
    return raw
