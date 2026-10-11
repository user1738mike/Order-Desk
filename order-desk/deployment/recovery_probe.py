"""Real TLS/session/private-byte persistence checks after owned restarts."""

# ruff: noqa: S101 -- executable acceptance checks; optimization forbidden.
import hashlib
import json
from pathlib import Path

from probe import request


def main():
    if not __debug__:
        raise RuntimeError("Do not optimize acceptance checks.")
    state = json.loads(Path("/run-state/workflow.json").read_text(encoding="utf-8"))
    cookies = json.loads(Path("/run-state/session.json").read_text(encoding="utf-8"))
    headers = {
        "Cookie": "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in cookies)
    }
    status, _, _ = request("/api/v1/workspaces/", headers=headers)
    assert status == 200, "Persisted session did not survive recreation."
    for artifact in (state["document"], state["artifact"]):
        status, response_headers, content = request(
            artifact["download_url"], headers=headers
        )
        assert status == 200
        assert hashlib.sha256(content).hexdigest() == artifact["sha256"]
        assert len(content) == artifact["size_bytes"]
        assert "no-store" in response_headers["Cache-Control"]
    status, _, content = request(state["document"]["extraction_url"], headers=headers)
    assert status == 200
    result = json.loads(content)
    assert (
        result["job"]["id"] == state["job"] and result["job"]["status"] == "succeeded"
    )
    print(
        "PASS: persisted secure session, private source/export digests and "
        "immutable extraction result survived restart/recreation."
    )


if __name__ == "__main__":
    main()
