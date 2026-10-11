"""Acceptance-only abrupt process exit at the real CSV parser entry."""

import argparse
import os
import sys
from uuid import UUID

import django

sys.path.insert(0, "/app")
django.setup()

from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402

from apps.accounts.models import User  # noqa: E402
from apps.orders import extraction_services  # noqa: E402
from apps.orders.csv_extraction import extract_csv  # noqa: E402

parser = argparse.ArgumentParser()
for name in ("actor", "workspace", "job"):
    parser.add_argument(f"--{name}", type=UUID, required=True)
arguments = parser.parse_args()
with connection.cursor() as cursor:
    cursor.execute("SELECT current_database(),current_user,session_user")
    if cursor.fetchone() != ("test_orderdesk", "orderdesk_app", "orderdesk_app"):
        raise RuntimeError("Interruption check requires isolated test runtime role.")
call_command("check_runtime_role")
# Only the acceptance invocation uses a short lease. All source/claim/terminal
# database guards stay active; real production commands retain 120 seconds.
extraction_services.LEASE_SECONDS = 2


def trace(frame, event, _argument):
    if event == "call" and frame.f_code is extract_csv.__code__:
        print(f"Abrupt parser-entry interruption: {arguments.job}", flush=True)
        os._exit(73)
    return trace


sys.settrace(trace)
extraction_services.process_extraction(
    actor=User.objects.get(pk=arguments.actor),
    organization_id=arguments.workspace,
    job_id=arguments.job,
)
raise RuntimeError("Expected actual parser-entry interruption was not reached.")
