"""Check database privileges before starting the local development server."""

import os
import sys
from pathlib import Path

import django
from django.core.management import call_command

# Direct script execution puts scripts/, rather than /app, on Python's path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
if os.environ["DJANGO_SETTINGS_MODULE"] != "config.settings.local":
    raise RuntimeError("run_dev_server.py may only run with local settings.")

django.setup()
call_command("check_runtime_role")
# A fixed interpreter and arguments replace this helper, preserving stop signals.
os.execv(  # noqa: S606
    sys.executable,
    [sys.executable, "manage.py", "runserver", "0.0.0.0:8000"],  # noqa: S104
)
