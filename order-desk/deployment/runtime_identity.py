"""Actual runtime identity, DB TLS and hostname validation; never print secrets."""

import os
import socket
import sys

import django
import psycopg

sys.path.insert(0, "/app")
django.setup()
from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402

call_command("check_runtime_role")
with connection.cursor() as cursor:
    cursor.execute(
        "SELECT current_user,session_user,ssl FROM pg_stat_ssl "
        "WHERE pid=pg_backend_pid()"
    )
    if cursor.fetchone() != ("orderdesk_app", "orderdesk_app", True):
        raise RuntimeError("Incorrect actual runtime/TLS identity.")
if os.getuid() != 10001:
    raise RuntimeError("Runtime process must use UID 10001.")
config = settings.DATABASES["default"]
try:
    psycopg.connect(
        dbname=config["NAME"],
        user=config["USER"],
        password=config["PASSWORD"],
        host="wrong-db-host.test",
        hostaddr=socket.gethostbyname("db"),
        sslmode="verify-full",
        sslrootcert=config["OPTIONS"]["sslrootcert"],
        connect_timeout=3,
    ).close()
except psycopg.OperationalError:
    pass
else:
    raise RuntimeError("Wrong database TLS hostname was accepted.")
print(
    "PASS: UID 10001; actual session/current role orderdesk_app; "
    "DB TLS and wrong-hostname rejection."
)
