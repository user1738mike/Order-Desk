"""Bounded local orphan recovery using metadata visibility and active-file leases."""

import fcntl
import os
import re
import stat
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.orders.models import OrderDocument
from apps.orders.private_documents import private_root


class Command(BaseCommand):
    help = "Reconcile at most 100 old private orphans; local maintenance role only."

    def add_arguments(self, parser):
        parser.add_argument("--offset", type=int, default=0)

    def handle(self, *args, **options):
        offset = options["offset"]
        if not 0 <= offset <= 100000:
            raise CommandError("Offset must be from 0 to 100000.")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user, session_user")
            database, current, session = cursor.fetchone()
        if (
            not settings.DEBUG
            or database not in {"orderdesk", "test_orderdesk"}
            or current != "orderdesk_migrator"
            or session != current
        ):
            raise CommandError(
                "Local maintenance credentials and an allowed database are required."
            )
        removed = inspected = 0
        cutoff = time.time() - 86400
        with private_root() as root, os.scandir(root) as entries:
            for index, entry in enumerate(entries):
                if index < offset:
                    continue
                inspected += 1
                if inspected > 1000 or removed >= 100:
                    break
                if not re.fullmatch(r"[0-9a-f]{32}", entry.name):
                    continue
                try:
                    descriptor = os.open(
                        entry.name,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                        dir_fd=root,
                    )
                except OSError:
                    continue
                try:
                    info = os.fstat(descriptor)
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or info.st_nlink != 1
                        or info.st_uid != os.getuid()
                        or info.st_mtime > cutoff
                    ):
                        continue
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        continue
                    if not OrderDocument.objects.filter(
                        file=f"intake/{entry.name}"
                    ).exists():
                        os.unlink(entry.name, dir_fd=root)
                        removed += 1
                finally:
                    os.close(descriptor)
            os.fsync(root)
        self.stdout.write(
            f"Inspected {min(inspected, 1000)} entries; removed {removed} old orphans; "
            f"next offset {offset + min(inspected, 1000)}. "
            "Restart at zero after a complete pass."
        )
