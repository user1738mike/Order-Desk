"""Fail closed before starting the synchronous application server."""

import os
import sys
import tempfile

import django
from django.core.management import call_command

if os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings.local_production":
    raise RuntimeError("Use the explicit local production settings module.")
sys.path.insert(0, "/app")
django.setup()
call_command("check", deploy=True, fail_level="WARNING")
call_command("check_runtime_role")
os.execv(  # noqa: S606 -- fixed installed binary, no shell or user command.
    "/opt/venv/bin/gunicorn",
    [
        "gunicorn",
        "config.wsgi:application",
        "--bind",
        "0.0.0.0:8000",
        "--workers",
        "4",
        "--worker-class",
        "sync",
        "--timeout",
        "30",
        "--graceful-timeout",
        "15",
        "--max-requests",
        "1000",
        "--max-requests-jitter",
        "50",
        "--worker-tmp-dir",
        tempfile.gettempdir(),
        "--error-logfile",
        "-",
        "--no-control-socket",
        "--forwarded-allow-ips",
        "*",
        "--limit-request-line",
        "4096",
        "--limit-request-fields",
        "64",
    ],
)
