"""Real TLS/session/private-byte persistence checks after owned restarts."""

# ruff: noqa: S101 -- executable acceptance checks; optimization forbidden.
import hashlib
import json
from http.cookies import SimpleCookie
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
    if incoming := state.get("incoming"):
        source = incoming["document"]
        status, _, content = request(source["download_url"], headers=headers)
        assert status == 200
        assert hashlib.sha256(content).hexdigest() == source["sha256"]
        assert len(content) == source["size_bytes"]
        foreign_url = source["download_url"].replace(
            incoming["workspace"], incoming["foreign_workspace"]
        )
        assert request(foreign_url, headers=headers)[0] == 404
        base = f"/api/v1/workspaces/{incoming['workspace']}/incoming/"
        status, _, content = request(
            base + "?operation_key=" + source["intake_key"], headers=headers
        )
        assert status == 200
        rows = json.loads(content)
        assert rows["count"] == 1
        assert rows["results"][0]["draft"] == incoming["draft_id"]
        status, _, content = request(source["extraction_url"], headers=headers)
        assert status == 200
        job = json.loads(content)["job"]
        assert job["id"] == incoming["job_id"] and job["status"] == "succeeded"
        status, csrf_headers, content = request("/api/v1/auth/csrf/", headers=headers)
        assert status == 200
        jar = SimpleCookie()
        jar.load(headers["Cookie"])
        if csrf_headers.get("Set-Cookie"):
            jar.load(csrf_headers["Set-Cookie"])
        mutation_headers = {
            "Cookie": "; ".join(f"{key}={value.value}" for key, value in jar.items()),
            "X-CSRFToken": json.loads(content)["csrf_token"],
            "Content-Type": "application/json",
            "Origin": "https://orderdesk.localhost:8443",
        }
        for url, payload, identity, expected in (
            (
                base + source["id"] + "/link/",
                incoming["link_payload"],
                "draft",
                incoming["draft_id"],
            ),
            (
                source["extraction_url"] + "apply/",
                incoming["apply_payload"],
                "application_id",
                incoming["application_id"],
            ),
        ):
            status, _, content = request(
                url,
                headers=mutation_headers,
                method="POST",
                body=json.dumps(payload).encode(),
            )
            assert status == 200 and json.loads(content)[identity] == expected
        status, _, content = request(
            f"/api/v1/workspaces/{incoming['workspace']}/draft-orders/"
            f"{incoming['draft_id']}/lines/",
            headers=headers,
        )
        assert status == 200
        lines = json.loads(content)
        assert lines["count"] == 1
        assert (
            lines["results"][0]["requested_sku"],
            lines["results"][0]["quantity"],
            lines["results"][0]["unit"],
        ) == ("00042", "1.250", "case")
        print(
            "PASS: incoming original/link/job/application and identical-operation "
            "replay survived recovery; foreign download denied."
        )
        if customer := state.get("customer"):
            customer_base = f"/api/v1/workspaces/{customer['workspace']}/customers/"
            for suffix, expected in (
                (customer["account_id"] + "/", "000007"),
                (
                    customer["account_id"] + "/locations/",
                    "000020",
                ),
            ):
                status, _, content = request(customer_base + suffix, headers=headers)
                assert status == 200 and expected.encode() in content
            status, _, content = request(
                customer_base + "resolve/?identifier=Recovery.Exact", headers=headers
            )
            assert status == 200
            matches = json.loads(content)["matches"]
            assert len(matches) == 1
            assert matches[0]["account"]["id"] == customer["account_id"]
            status, _, content = request(
                customer_base + "operations/" + customer["receipt_key"] + "/",
                headers=headers,
            )
            assert status == 200
            assert json.loads(content)["response"]["id"] == customer["account_id"]
            confirmation_url = (
                customer_base + "drafts/" + customer["draft_id"] + "/confirmation/"
            )
            status, _, content = request(
                confirmation_url,
                headers=mutation_headers,
                method="POST",
                body=json.dumps(customer["confirmation"]).encode(),
            )
            assert (
                status == 200 and json.loads(content)["id"] == customer["decision_id"]
            )
            status, _, content = request(confirmation_url + "history/", headers=headers)
            assert status == 200 and json.loads(content)["count"] == 1
            snapshot_url = (
                customer_base + "orders/" + customer["order_id"] + "/snapshot/"
            )
            status, _, content = request(snapshot_url, headers=headers)
            assert status == 200
            frozen = json.loads(content)["snapshot"]
            assert frozen["id"] == customer["snapshot_id"]
            assert frozen["payload"] == customer["payload"]
            assert frozen["payload"]["location"]["id"] == customer["site_id"]
            assert (
                request(
                    snapshot_url.replace(
                        customer["workspace"], incoming["foreign_workspace"]
                    ),
                    headers=headers,
                )[0]
                == 404
            )
            print(
                "PASS: customer account/site/alias and durable reference receipt, "
                "identical confirmation replay and frozen snapshot survived recovery."
            )
    print(
        "PASS: persisted secure session, private source/export digests and "
        "immutable extraction result survived restart/recreation."
    )


if __name__ == "__main__":
    main()
