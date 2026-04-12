"""
Secrets manager — OCI Vault with .env fallback.

Priority (highest to lowest):
  1. OCI Vault (if OCI_VAULT_ID is set and reachable)
  2. os.environ / .env (always available — local dev, Docker without Vault)

Usage:
  from config.secrets import load_vault_secrets, set_secret

  # Call once at process startup (before settings.py reads os.environ):
  load_vault_secrets()

  # Update a secret at runtime (e.g. new Kite token after daily login):
  set_secret("KITE_ACCESS_TOKEN", new_token)   # writes Vault + .env

Design:
  - Fail-open: if Vault is unreachable, the process continues with .env values.
  - Idempotent: calling load_vault_secrets() multiple times is safe (cached after first call).
  - Thread-safe: uses a module-level lock.

Which vars go in Vault (set by oci_vault_push.py):
  KITE_API_KEY, KITE_API_SECRET, KITE_ACCESS_TOKEN
  ZERODHA_USER_ID, ZERODHA_PASSWORD, ZERODHA_TOTP_SECRET
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

Which vars stay in .env (Docker Compose reads them directly at startup):
  POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, DATABASE_URL
  TRADING_MODE, VIRTUAL_CAPITAL, NEXT_PUBLIC_DASHBOARD_API_URL
  OCI_VAULT_ID  (not a secret — just tells this module which vault to use)
"""

from __future__ import annotations

import base64
import os
import re
import threading
from pathlib import Path
from typing import Optional

from loguru import logger

_ENV_FILE  = Path(__file__).resolve().parent.parent / ".env"
_lock      = threading.Lock()
_loaded    = False

# Secrets that belong in Vault (all others stay in .env)
VAULT_KEYS = {
    "KITE_API_KEY",
    "KITE_API_SECRET",
    "KITE_ACCESS_TOKEN",
    "ZERODHA_USER_ID",
    "ZERODHA_PASSWORD",
    "ZERODHA_TOTP_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
}


# ── Public API ────────────────────────────────────────────────────────────────

def load_vault_secrets() -> bool:
    """
    Fetch all secrets from OCI Vault and inject them into os.environ.
    Returns True if Vault was used, False if falling back to .env.
    Call once at process start, before config.settings is imported.
    """
    global _loaded
    with _lock:
        if _loaded:
            return False
        ok = _load()
        _loaded = True
        return ok


def set_secret(key: str, value: str) -> None:
    """
    Update a secret in Vault (if configured) AND in the local .env file.
    Used for daily KITE_ACCESS_TOKEN refresh.
    """
    os.environ[key] = value
    _update_env_file(key, value)

    vault_id = os.environ.get("OCI_VAULT_ID", "").strip()
    if not vault_id:
        return

    try:
        _vault_upsert(vault_id, key, value)
    except Exception as exc:
        logger.debug(f"secrets.set_secret: Vault update skipped — {exc}")


# ── Internal ──────────────────────────────────────────────────────────────────

def _load() -> bool:
    vault_id = os.environ.get("OCI_VAULT_ID", "").strip()
    if not vault_id:
        logger.debug("secrets: OCI_VAULT_ID not set — using .env only")
        return False

    try:
        import oci as _oci
    except ImportError:
        logger.debug("secrets: 'oci' package not installed — using .env only")
        return False

    try:
        config   = _oci.config.from_file()
        vault_c  = _oci.vault.VaultsClient(config)
        secret_c = _oci.secrets.SecretsClient(config)
        comp_id  = config.get("tenancy")

        secrets = vault_c.list_secrets(
            compartment_id=comp_id,
            vault_id=vault_id,
            lifecycle_state="ACTIVE",
        ).data

        loaded = 0
        for s in secrets:
            if s.secret_name not in VAULT_KEYS:
                continue
            try:
                bundle  = secret_c.get_secret_bundle(s.id).data
                content = bundle.secret_bundle_content.content
                value   = base64.b64decode(content).decode("utf-8")
                os.environ[s.secret_name] = value
                loaded += 1
            except Exception as exc:
                logger.warning(f"secrets: could not fetch '{s.secret_name}' from Vault — {exc}")

        logger.info(f"secrets: loaded {loaded} secrets from OCI Vault")
        return True

    except Exception as exc:
        logger.warning(f"secrets: Vault unreachable — falling back to .env ({exc})")
        return False


def _vault_upsert(vault_id: str, key: str, value: str) -> None:
    """Create or update a secret in Vault."""
    import oci as _oci

    config   = _oci.config.from_file()
    vault_c  = _oci.vault.VaultsClient(config)
    comp_id  = config.get("tenancy")
    encoded  = base64.b64encode(value.encode()).decode()

    # Find existing secret
    existing = vault_c.list_secrets(
        compartment_id=comp_id,
        vault_id=vault_id,
        name=key,
        lifecycle_state="ACTIVE",
    ).data

    if existing:
        vault_c.update_secret(
            secret_id=existing[0].id,
            update_secret_details=_oci.vault.models.UpdateSecretDetails(
                secret_content=_oci.vault.models.Base64SecretContentDetails(
                    content_type="BASE64",
                    content=encoded,
                )
            ),
        )
        logger.debug(f"secrets: updated Vault secret '{key}'")
    else:
        # Need key_id to create — fetch from vault metadata
        vault_meta = vault_c.get_vault(vault_id).data
        key_id     = vault_meta.wrapping_key_id

        vault_c.create_secret(
            create_secret_details=_oci.vault.models.CreateSecretDetails(
                compartment_id=comp_id,
                secret_name=key,
                vault_id=vault_id,
                key_id=key_id,
                secret_content=_oci.vault.models.Base64SecretContentDetails(
                    content_type="BASE64",
                    content=encoded,
                ),
            )
        )
        logger.debug(f"secrets: created Vault secret '{key}'")


def _update_env_file(key: str, value: str) -> None:
    """Write key=value to .env (fallback persistence)."""
    try:
        content = _ENV_FILE.read_text(encoding="utf-8") if _ENV_FILE.exists() else ""
        pattern = rf"^{re.escape(key)}\s*=.*$"
        replacement = f"{key}={value}"
        if re.search(pattern, content, flags=re.MULTILINE):
            content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        else:
            content = content.rstrip("\n") + f"\n{replacement}\n"
        _ENV_FILE.write_text(content, encoding="utf-8")
    except Exception as exc:
        logger.debug(f"secrets: .env write failed — {exc}")
