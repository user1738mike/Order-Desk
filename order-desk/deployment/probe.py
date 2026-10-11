"""Validate the real TLS proxy with explicit CA/hostname trust, no bypass."""

# Ruff: this is an executable acceptance test, not an application handler.
# ruff: noqa: S101

import http.client
import json
import re
import socket
import ssl

HOST = "orderdesk.localhost"


def request(path, *, headers=None, body=None, method="GET", context=None):
    connection = http.client.HTTPSConnection(
        HOST,
        8443,
        timeout=8,
        context=context or ssl.create_default_context(cafile="/trust/ca.crt"),
    )
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


def main():
    if not __debug__:
        raise RuntimeError("Run acceptance checks without Python optimization.")
    # The default public trust store must reject this private local issuer.
    try:
        request("/", context=ssl.create_default_context())
    except ssl.SSLCertVerificationError:
        pass
    else:
        raise AssertionError("Unexpected public trust of the local certificate.")
    try:
        with socket.create_connection(("proxy", 8443), timeout=5) as raw:
            ssl.create_default_context(cafile="/trust/ca.crt").wrap_socket(
                raw, server_hostname="attacker.test"
            )
    except ssl.SSLCertVerificationError:
        pass
    else:
        raise AssertionError("Wrong TLS hostname was accepted.")
    for route in ("/api/v1/health/live/", "/api/v1/health/ready/"):
        status, headers, data = request(route)
        assert status == 200 and json.loads(data) == {"status": "ok"}
        assert "no-store" in headers["Cache-Control"]
    status, headers, shell = request(
        "/",
        headers={
            "X-Forwarded-Proto": "http",
            "Forwarded": "host=attacker.test;proto=http",
            "X-Forwarded-Host": "attacker.test",
        },
    )
    assert status == 200
    assert headers["Strict-Transport-Security"] == "max-age=60"
    assert "unsafe-inline" not in headers["Content-Security-Policy"]
    assets = re.findall(rb'(?:src|href)="(/static/[^"]+)"', shell)
    assert assets
    for asset in assets:
        path = asset.decode()
        assert re.search(r"\.[0-9a-f]{12}\.", path), path
        asset_status, asset_headers, _ = request(path)
        assert asset_status == 200
        assert "immutable" in asset_headers["Cache-Control"]
    assert request("/api/v1/unknown-route/")[0] == 404
    assert request("/not-an-asset/")[0] == 404
    for path in (
        "/media/source.pdf",
        "/private-documents/source.pdf",
        "/intake/file",
        "/exports/file",
        "/static/../private-documents/source.pdf",
    ):
        assert request(path)[0] == 404
    assert request("/", headers={"Host": "attacker.test"})[0] == 421
    assert request("/api/v1/workspaces/")[0] == 403
    status, headers, data = request("/api/v1/auth/csrf/")
    assert status == 200
    assert "Secure" in headers["Set-Cookie"] and "SameSite=Lax" in headers["Set-Cookie"]
    token = json.loads(data)["csrf_token"]
    assert (
        request(
            "/api/v1/auth/login/",
            method="POST",
            body=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-CSRFToken": token,
                "Cookie": headers["Set-Cookie"].split(";")[0],
                "Origin": "https://attacker.test",
            },
        )[0]
        == 403
    )
    assert (
        request(
            "/api/v1/auth/login/", method="POST", body=b"x" * (11 * 1024 * 1024 + 1)
        )[0]
        == 413
    )
    connection = http.client.HTTPConnection(HOST, 8080, timeout=8)
    connection.request(
        "GET", "/api/v1/health/live/", headers={"X-Forwarded-Proto": "https"}
    )
    response = connection.getresponse()
    assert response.status == 308
    assert (
        response.getheader("Location")
        == "https://orderdesk.localhost:8443/api/v1/health/live/"
    )
    connection.close()
    print(
        "PASS: trusted TLS hostname/chain; static manifest; proxy headers/Host; "
        "cookies/CSRF; private paths; body limit; HTTP redirect."
    )


if __name__ == "__main__":
    main()
