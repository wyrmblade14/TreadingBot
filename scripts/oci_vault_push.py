"""
One-time script — push secrets from .env into OCI Vault.

Run this ONCE after `make oci-setup-services` has created your Vault:

    python3 scripts/oci_vault_push.py

After this, the bot will load all VAULT_KEYS from Vault at startup,
and fall back to .env if Vault is unreachable.

Requirements:
  - OCI_VAULT_ID set in .env  (or passed as OCI_VAULT_ID env var)
  - ~/.oci/config + API key on disk  (created by: oci setup config)
  - oci Python package installed:   pip install oci

Which keys are pushed:
  See VAULT_KEYS in config/secrets.py — Kite + Zerodha + Telegram secrets.
  Database passwords and non-secret config stay in .env.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── project root on path ──────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from loguru import logger
from config.secrets import VAULT_KEYS, _vault_upsert


def main() -> None:
    vault_id = os.environ.get("OCI_VAULT_ID", "").strip()
    if not vault_id:
        print(
            "ERROR: OCI_VAULT_ID is not set.\n"
            "  1. Run:  make oci-setup-services\n"
            "  2. Copy the Vault OCID printed at the end into your .env:\n"
            "       OCI_VAULT_ID=ocid1.vault.oc1...\n"
            "  3. Re-run this script."
        )
        sys.exit(1)

    try:
        import oci  # noqa: F401
    except ImportError:
        print("ERROR: 'oci' package not installed.  Run:  pip install oci")
        sys.exit(1)

    print(f"Pushing {len(VAULT_KEYS)} secrets to Vault {vault_id[:32]}...")
    print()

    pushed = 0
    skipped = 0
    failed = 0

    for key in sorted(VAULT_KEYS):
        value = os.environ.get(key, "").strip()
        if not value:
            print(f"  SKIP  {key}  (not set in .env)")
            skipped += 1
            continue
        try:
            _vault_upsert(vault_id, key, value)
            # Mask the value for display
            display = value[:4] + "…" if len(value) > 4 else "***"
            print(f"  OK    {key}={display}")
            pushed += 1
        except Exception as exc:
            print(f"  FAIL  {key}  — {exc}")
            failed += 1

    print()
    print(f"Done: {pushed} pushed, {skipped} skipped (blank), {failed} failed.")

    if failed:
        print("\nCheck your OCI credentials and Vault OCID, then re-run.")
        sys.exit(1)
    else:
        print(
            "\nSecrets are now in Vault.\n"
            "The bot will load them automatically at startup.\n"
            "You can blank out these values in .env (keep OCI_VAULT_ID)."
        )


if __name__ == "__main__":
    main()
