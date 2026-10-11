"""One-shot private local CA, distinct DB/proxy keys, and storage ownership."""

import os
import subprocess
from pathlib import Path


def openssl(*arguments):
    subprocess.run(  # noqa: S603
        ["/usr/bin/openssl", *arguments],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def initialize():
    os.umask(0o077)
    os.chown("/private-documents", 10001, 10001)
    os.chmod("/private-documents", 0o700)
    ca = Path("/issuer")
    complete = ca / "complete"
    if complete.exists():
        for certificate in ("/db-tls/server.crt", "/proxy-tls/server.crt"):
            openssl("x509", "-in", certificate, "-noout", "-checkend", "86400")
        print("Existing local certificates preserved.")
        return
    if any(ca.iterdir()):
        raise RuntimeError(
            "Incomplete certificate initialization; inspect owned volumes."
        )
    openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:3072",
        "-sha256",
        "-nodes",
        "-keyout",
        "/issuer/ca.key",
        "-out",
        "/issuer/ca.crt",
        "-days",
        "30",
        "-subj",
        "/CN=Order Desk isolated local CA",
        "-addext",
        "basicConstraints=critical,CA:TRUE,pathlen:0",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
    )
    Path("/trust/ca.crt").write_bytes(Path("/issuer/ca.crt").read_bytes())
    os.chmod("/trust/ca.crt", 0o444)
    for directory, hostname, uid in (
        ("/db-tls", "db", 999),
        ("/proxy-tls", "orderdesk.localhost", 101),
    ):
        openssl(
            "req",
            "-new",
            "-newkey",
            "rsa:3072",
            "-nodes",
            "-sha256",
            "-keyout",
            f"{directory}/server.key",
            "-out",
            "/issuer/server.csr",
            "-subj",
            f"/CN={hostname}",
        )
        extension = ca / "extensions"
        extension.write_text(
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            f"extendedKeyUsage=serverAuth\nsubjectAltName=DNS:{hostname}\n",
            encoding="ascii",
        )
        openssl(
            "x509",
            "-req",
            "-in",
            "/issuer/server.csr",
            "-CA",
            "/issuer/ca.crt",
            "-CAkey",
            "/issuer/ca.key",
            "-CAcreateserial",
            "-out",
            f"{directory}/server.crt",
            "-days",
            "14",
            "-sha256",
            "-extfile",
            str(extension),
        )
        for name in ("server.key", "server.crt"):
            os.chown(f"{directory}/{name}", uid, uid)
            os.chmod(f"{directory}/{name}", 0o600 if name.endswith("key") else 0o444)
        os.chown(directory, uid, uid)
        os.chmod(directory, 0o700)
    os.chown("/private-documents", 10001, 10001)
    os.chmod("/private-documents", 0o700)
    complete.touch()
    print("Local certificates and private storage initialized; no host trust changes.")


if __name__ == "__main__":
    initialize()
