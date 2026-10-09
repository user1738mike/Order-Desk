"""Route existing FileField reads to private intake without relocating legacy bytes."""

import os

from django.core.exceptions import SuspiciousFileOperation
from django.core.files import File
from django.core.files.storage import FileSystemStorage

from apps.orders.private_documents import KEY, open_document, private_root


class DocumentSourceStorage(FileSystemStorage):
    def _open(self, name, mode="rb"):
        if name.startswith("intake/"):
            if mode != "rb":
                raise SuspiciousFileOperation("Private source bytes are immutable.")
            return File(open_document(name, self.size(name)), name=name)
        return super()._open(name, mode)

    def size(self, name):
        if not name.startswith("intake/"):
            return super().size(name)
        match = KEY.fullmatch(name)
        if not match:
            raise SuspiciousFileOperation("Invalid private storage key.")
        with private_root() as root:
            descriptor = os.open(
                match[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root
            )
        try:
            return os.fstat(descriptor).st_size
        finally:
            os.close(descriptor)

    def exists(self, name):
        if name.startswith("intake/"):
            try:
                self.size(name)
                return True
            except FileNotFoundError:
                return False
        return super().exists(name)

    def save(self, name, content, max_length=None):
        if name and name.startswith("intake/"):
            raise SuspiciousFileOperation("Use authorized private intake.")
        return super().save(name, content, max_length=max_length)

    def delete(self, name):
        if name.startswith("intake/"):
            raise SuspiciousFileOperation(
                "Private sources require leased reconciliation."
            )
        return super().delete(name)

    def url(self, name):
        if name.startswith("intake/"):
            raise SuspiciousFileOperation("Private sources have no public URL.")
        return super().url(name)

    def path(self, name):
        if name.startswith("intake/"):
            raise SuspiciousFileOperation("Private sources have no public path.")
        return super().path(name)
