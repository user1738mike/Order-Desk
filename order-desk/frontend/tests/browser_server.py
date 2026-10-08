"""Observe the browser's actual peer budget without altering HTTP/auth behavior."""

import json
from pathlib import Path

from django.core.wsgi import get_wsgi_application

from apps.accounts.login_limits import login_bucket_key
from apps.accounts.models import LoginAttemptBucket

django_application = get_wsgi_application()


def application(environ, start_response):
    if environ.get("PATH_INFO") == "/api/v1/auth/login/":
        fixture_file = Path("var/frontend_browser_fixture.json")
        data = json.loads(fixture_file.read_text(encoding="utf-8"))
        key = login_bucket_key("peer", environ["REMOTE_ADDR"])
        peers = data.setdefault("peer_budgets", {})
        if key not in peers:
            peers[key] = not LoginAttemptBucket.objects.filter(key=key).exists()
            fixture_file.write_text(json.dumps(data), encoding="utf-8")
    return django_application(environ, start_response)
