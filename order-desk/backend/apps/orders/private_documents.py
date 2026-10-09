"""Private, immutable local intake. Linux dir-fd operations fail closed elsewhere."""

import csv
import fcntl
import hashlib
import io
import logging
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError

from apps.orders.document_files import MAX_ORDER_DOCUMENT_BYTES, OrderDocumentTooLarge

KEY = re.compile(r"intake/([0-9a-f]{32})\Z")
logger = logging.getLogger(__name__)


def original_filename(value: str) -> str:
    # Display metadata only; never use this to address storage.
    value = str(value).replace("\\", "/").rsplit("/", 1)[-1]
    value = "".join(char for char in value if char.isprintable()).strip()[:255]
    return value or "source-document"


@contextmanager
def private_root():
    root = Path(settings.PRIVATE_DOCUMENT_ROOT)
    if not root.is_absolute() or ".." in root.parts:
        raise OSError("Invalid private storage configuration.")
    public_roots = [
        settings.STATIC_ROOT,
        settings.MEDIA_ROOT,
        *settings.STATICFILES_DIRS,
    ]
    for public in public_roots:
        public = public[1] if isinstance(public, tuple) else public
        if root.is_relative_to(Path(public).absolute()):
            raise OSError("Private storage must be outside public and legacy roots.")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(root.parts[1:]):
            if index == len(root.parts) - 2:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise OSError("Private storage permissions are not configured.")
        yield descriptor
    finally:
        os.close(descriptor)


def validate_content(stream, filename):
    extension = Path(filename).suffix.lower()
    stream.seek(0)
    if extension == ".pdf":
        if not re.fullmatch(rb"%PDF-(?:1\.[0-7]|2\.0)[\r\n]", stream.read(9)):
            raise ValidationError(
                {"file": ["Provide a PDF with a supported signature."]}
            )
        stream.seek(max(0, stream.seek(0, 2) - 2048))
        if not stream.read().rstrip().endswith(b"%%EOF"):
            raise ValidationError({"file": ["The PDF end marker is missing."]})
        content_type = "application/pdf"
    elif extension == ".csv":
        stream.seek(0)
        text = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")

        def lines():
            while line := text.readline(65537):
                if len(line) > 65536 or any(
                    ord(char) < 32 and char not in "\t\r\n" for char in line
                ):
                    raise ValueError
                yield line

        try:
            width = None
            count = 0
            for row in csv.reader(lines(), strict=True):
                count += 1
                if (
                    count > 10000
                    or not 2 <= len(row) <= 128
                    or any(len(cell) > 4096 for cell in row)
                ):
                    raise ValueError
                if width is not None and len(row) != width:
                    raise ValueError
                width = len(row)
            if count == 0:
                raise ValueError
        except (UnicodeError, csv.Error, ValueError) as error:
            raise ValidationError(
                {"file": ["Provide bounded, rectangular UTF-8 CSV with 2–128 columns."]}
            ) from error
        finally:
            text.detach()
        content_type = "text/csv"
    else:
        raise ValidationError({"file": ["Only PDF and CSV intake is supported."]})
    stream.seek(0)
    return content_type


@contextmanager
def staged_document(upload):
    """Hold an OS lease through commit; orphan recovery cannot unlink an active file."""
    key = uuid4().hex
    with private_root() as root:
        descriptor = os.open(
            key, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root
        )
        keep = False
        state = {}
        with os.fdopen(descriptor, "w+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                upload.seek(0)
                received = 0
                digest = hashlib.sha256()
                while chunk := upload.read(
                    min(65536, MAX_ORDER_DOCUMENT_BYTES + 1 - received)
                ):
                    received += len(chunk)
                    if received > MAX_ORDER_DOCUMENT_BYTES:
                        raise OrderDocumentTooLarge()
                    stream.write(chunk)
                    digest.update(chunk)
                if received == 0:
                    raise ValidationError({"file": ["Empty files are not accepted."]})
                stream.flush()
                name = original_filename(upload.name)
                content_type = validate_content(stream, name)
                os.fchmod(stream.fileno(), 0o400)
                os.fsync(stream.fileno())
                os.fsync(root)
                state = {
                    "key": f"intake/{key}",
                    "size": received,
                    "name": name,
                    "content_type": content_type,
                    "committed": False,
                    "sha256": digest.hexdigest(),
                }
                yield state
                keep = state["committed"]
            finally:
                if not keep and not state.get("commit_attempt", False):
                    # Crashes release flock; age-based recovery owns the orphan.
                    try:
                        os.unlink(key, dir_fd=root)
                        os.fsync(root)
                    except OSError:
                        logger.error(
                            "Private document cleanup requires reconciliation."
                        )


def open_document(key, size, expected_digest=None):
    match = KEY.fullmatch(key)
    if not match:
        raise OSError("Document storage is unavailable.")
    with private_root() as root:
        descriptor = os.open(
            match[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root
        )
    stream = None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o400
            or info.st_size != size
            or not 0 < size <= MAX_ORDER_DOCUMENT_BYTES
        ):
            raise OSError("Document storage is unavailable.")
        stream = os.fdopen(descriptor, "rb")
        if expected_digest is not None:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
            if digest.hexdigest() != expected_digest:
                stream.close()
                raise OSError("Document source integrity failed.")
            stream.seek(0)
        return stream
    except Exception:
        if stream is None:
            os.close(descriptor)
        else:
            stream.close()
        raise
