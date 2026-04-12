# OCI Management & Infrastructure

This directory contains scripts and configuration for deploying TreadingBot to Oracle Cloud Infrastructure (OCI) and managing backups.

## Directory Structure

- `provision.sh`: Fully automated script to create VCN, Subnets, Security Lists, and a VM.Standard.A1.Flex instance.
- `setup_services.sh`: Creates free-tier OCI services: Object Storage bucket (for backups) and OCI Vault (for secrets).
- `vault_push.py`: Pushes local `.env` secrets to the OCI Vault.
- `backup.sh`: Dumps the PostgreSQL database and uploads it to OCI Object Storage.
- `restore.sh`: Downloads a backup from OCI and restores it to the database.

## Common Commands (via Makefile)

- `make oci-provision`: Provision the cloud instance.
- `make oci-setup-services`: Setup Object Storage and Vault.
- `make oci-vault-push`: Sync secrets to the cloud.
- `make oci-backup`: Manual database backup.
- `make db-restore DATE=YYYY-MM-DD`: Restore from a specific date.

## Requirements

- OCI CLI installed: `pip install oci-cli`
- OCI CLI configured: `oci setup config`
- Python `oci` package: `pip install oci`
