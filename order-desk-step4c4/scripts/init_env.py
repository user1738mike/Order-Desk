"""Create or extend local .env without replacing existing credentials."""

import os
import re
import secrets
import sys
import tempfile
from pathlib import Path

SECRET_KEYS = {
    "POSTGRES_PASSWORD",
    "DATABASE_MIGRATION_PASSWORD",
    "DATABASE_APP_PASSWORD",
    "DJANGO_SECRET_KEY",
}
ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def assignments(contents: str) -> dict[str, str]:
    result = {}
    for line in contents.splitlines():
        match = ASSIGNMENT.fullmatch(line)
        if match:
            key, value = match.groups()
            if key in result:
                raise ValueError(
                    f"Duplicate {key} assignment; fix .env before retrying."
                )
            result[key] = value
    return result


def extend_environment(template: str, existing: str | None) -> str:
    defaults = assignments(template)
    if not SECRET_KEYS <= defaults.keys():
        raise ValueError("The .env.example template is missing required secret fields.")
    if existing is None:
        contents = template
        current = defaults
    else:
        contents = existing
        current = assignments(existing)
        # A new bootstrap password would not match the already initialized volume.
        if not current.get("POSTGRES_PASSWORD", "").strip().strip("\"'"):
            raise ValueError("Existing .env needs its original POSTGRES_PASSWORD.")

    for key, default in defaults.items():
        if key not in current:
            value = secrets.token_urlsafe(64) if key in SECRET_KEYS else default
            contents = contents.rstrip("\n") + f"\n{key}={value}\n"
        elif key in SECRET_KEYS and not current[key].strip().strip("\"'"):
            value = secrets.token_urlsafe(64)
            contents = re.sub(
                rf"^{key}=.*$", f"{key}={value}", contents, flags=re.MULTILINE
            )
    return contents


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    destination = project_root / ".env"
    temporary: Path | None = None
    try:
        template = (project_root / ".env.example").read_text(encoding="utf-8")
        original = (
            destination.read_text(encoding="utf-8") if destination.exists() else None
        )
        contents = extend_environment(template, original)
        if contents == original:
            print(".env is complete; existing values were preserved.")
            return 0

        # Write atomically so interruption cannot truncate the existing password.
        # On Windows, the project directory's ACLs govern access to this file.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=".env.tmp-",  # Also ignored by Git if the process is interrupted.
            dir=project_root,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        if destination.exists() and destination.read_text(encoding="utf-8") != original:
            raise ValueError(
                ".env changed during setup; retry after other edits finish."
            )
        if original is None and destination.exists():
            raise ValueError(".env was created during setup; retry to preserve it.")
        os.replace(temporary, destination)
        temporary = None
    except (OSError, ValueError) as error:
        message = (
            str(error)
            if isinstance(error, ValueError)
            else "Cannot safely update .env."
        )
        print(message, file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print("Updated .env; existing values were preserved and missing secrets generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
