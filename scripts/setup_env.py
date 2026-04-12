"""
Automated credential setup — run once before `docker-compose up`.

What it does:
  1. Reads .env
  2. If POSTGRES_PASSWORD is still the placeholder (or missing), generates a
     cryptographically secure 32-character random password.
  3. Writes the new password into both POSTGRES_PASSWORD and DATABASE_URL so
     they are always in sync.
  4. Does nothing if a non-placeholder password is already set (idempotent).

Usage:
    python scripts/setup_env.py          # auto-generates if needed
    python scripts/setup_env.py --force  # regenerate even if already set

After this script, just run:
    docker-compose up -d
"""

from __future__ import annotations

import argparse
import re
import secrets
import string
import sys
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

_ENV_PATH       = Path(__file__).parent.parent / ".env"
_PLACEHOLDER    = "changeme_before_production"
_PW_ALPHABET    = string.ascii_letters + string.digits  # no special chars — safe in URLs
_PW_LENGTH      = 32

# ── Helpers ───────────────────────────────────────────────────────────────────

def _generate_password() -> str:
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(_PW_LENGTH))


def _read_env(path: Path) -> list[str]:
    if not path.exists():
        sys.exit(f"ERROR: {path} not found. Copy .env.example to .env first.")
    return path.read_text().splitlines(keepends=True)


def _get_value(lines: list[str], key: str) -> str | None:
    for line in lines:
        m = re.match(rf"^{re.escape(key)}=(.*)\s*$", line)
        if m:
            return m.group(1).strip()
    return None


def _set_value(lines: list[str], key: str, value: str) -> list[str]:
    """Replace the value of an existing key, or append if key not present."""
    new_lines = []
    replaced = False
    for line in lines:
        if re.match(rf"^{re.escape(key)}=", line):
            new_lines.append(f"{key}={value}\n")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f"{key}={value}\n")
    return new_lines


def _update_database_url(lines: list[str], new_password: str) -> list[str]:
    """Swap the password portion of DATABASE_URL in-place."""
    new_lines = []
    for line in lines:
        if re.match(r"^DATABASE_URL=", line):
            # Replace :anything@ with :newpassword@
            updated = re.sub(r"(postgresql://[^:]+:)[^@]+(@)", rf"\g<1>{new_password}\2", line)
            new_lines.append(updated)
        else:
            new_lines.append(line)
    return new_lines


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate PostgreSQL credentials into .env")
    parser.add_argument("--force", action="store_true", help="Regenerate even if already set")
    args = parser.parse_args()

    lines = _read_env(_ENV_PATH)
    current_pw = _get_value(lines, "POSTGRES_PASSWORD")

    if current_pw and current_pw != _PLACEHOLDER and not args.force:
        print(f"[setup_env] POSTGRES_PASSWORD is already set — nothing to do.")
        print(f"[setup_env] Use --force to regenerate.")
        return

    new_password = _generate_password()

    lines = _set_value(lines, "POSTGRES_PASSWORD", new_password)
    lines = _update_database_url(lines, new_password)

    _ENV_PATH.write_text("".join(lines))

    action = "Regenerated" if (current_pw and current_pw != _PLACEHOLDER) else "Generated"
    print(f"[setup_env] {action} POSTGRES_PASSWORD ({_PW_LENGTH} chars) → .env updated.")
    print(f"[setup_env] DATABASE_URL password synced.")

    # If the postgres container is already running with old data, the POSTGRES_PASSWORD
    # env var has no effect — postgres only reads it on first init. Sync the password
    # into the running instance via ALTER USER so .env and the DB always stay in sync.
    _sync_postgres_password(new_password)

    print(f"[setup_env] Ready: docker-compose up -d")


def _sync_postgres_password(password: str) -> None:
    """If the postgres container is running, update the DB user's password to match."""
    import subprocess
    result = subprocess.run(
        ["docker", "exec", "treadingbot_postgres",
         "psql", "-U", "treadingbot", "-d", "treadingbot",
         "-c", f"ALTER USER treadingbot WITH PASSWORD '{password}';"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("[setup_env] Live postgres user password updated (ALTER USER).")
    # If container isn't running, that's fine — the new password will be used on first start.


if __name__ == "__main__":
    main()
