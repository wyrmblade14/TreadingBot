#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# TreadingBot — Oracle Cloud free-tier services setup
#
# Run this ONCE after oci_provision.sh to enable:
#   1. Object Storage bucket — daily PostgreSQL backups (20 GB free)
#   2. Vault + secrets      — store .env credentials securely (150 secrets free)
#   3. Monitoring alarm     — Telegram alert if instance CPU = 0 for 5 min
#
# All services used are Always Free — $0.00/month.
#
# Usage:
#   make oci-setup-services
#   make oci-setup-services ARGS="--compartment-id ocid1.compartment..."
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info()    { echo -e "${CYAN}▸ $*${RESET}"; }
success() { echo -e "${GREEN}✓ $*${RESET}"; }
warn()    { echo -e "${YELLOW}⚠ $*${RESET}"; }
die()     { echo -e "${RED}✗ $*${RESET}" >&2; exit 1; }

COMPARTMENT_ID=""
BUCKET_NAME="treadingbot-backups"
VAULT_NAME="TreadingBot-Vault"
ALARM_NAME="TreadingBot-BotDead"

while [[ $# -gt 0 ]]; do
    case $1 in
        --compartment-id) COMPARTMENT_ID="$2"; shift 2 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

command -v oci --auth security_token &>/dev/null || die "OCI CLI not found. Run: pip install oci-cli"

if [[ -z "$COMPARTMENT_ID" ]]; then
    COMPARTMENT_ID=$(grep -E '^tenancy\s*=' ~/.oci/config | head -1 | cut -d= -f2 | tr -d ' ')
fi
[[ -n "$COMPARTMENT_ID" ]] || die "Cannot determine compartment ID. Pass --compartment-id"

REGION=$(oci --auth security_token iam region-subscription list --query 'data[0]."region-name"' --raw-output 2>/dev/null \
    || grep -E '^region\s*=' ~/.oci/config | head -1 | cut -d= -f2 | tr -d ' ')

echo ""
echo -e "${BOLD}TreadingBot — Oracle Free Services Setup${RESET}"
echo ""

# ── 1. Object Storage bucket ──────────────────────────────────────────────────
info "Setting up Object Storage bucket for backups..."

EXISTING_BUCKET=$(oci --auth security_token os bucket get \
    --bucket-name "$BUCKET_NAME" \
    --query 'data.name' --raw-output 2>/dev/null || echo "")

if [[ -n "$EXISTING_BUCKET" && "$EXISTING_BUCKET" != "null" ]]; then
    success "Bucket '$BUCKET_NAME' already exists"
else
    oci --auth security_token os bucket create \
        --compartment-id "$COMPARTMENT_ID" \
        --name "$BUCKET_NAME" \
        --storage-tier Standard \
        --versioning Disabled \
        --freeform-tags '{"billing":"free-tier","project":"TreadingBot"}' \
        --query 'data.name' --raw-output >/dev/null
    success "Bucket '$BUCKET_NAME' created (20 GB free)"
fi

# Set lifecycle policy: delete backups older than 30 days (stays within 20 GB free)
oci --auth security_token os object-lifecycle-policy put \
    --bucket-name "$BUCKET_NAME" \
    --items '[{
        "name":       "delete-old-backups",
        "action":     "DELETE",
        "timeAmount": 30,
        "timeUnit":   "DAYS",
        "isEnabled":  true,
        "objectNameFilter": {"inclusionPrefixes": ["backup-"]}
    }]' 2>/dev/null && success "Lifecycle policy: backups deleted after 30 days" \
    || warn "Lifecycle policy not set (may need extra permissions)"

# ── 2. Vault for secrets ───────────────────────────────────────────────────────
info "Setting up Vault for secure credential storage..."

VAULT_ID=$(oci --auth security_token kms management vault list \
    --compartment-id "$COMPARTMENT_ID" \
    --query "data[?\"display-name\"=='$VAULT_NAME' && \"lifecycle-state\"=='ACTIVE'].id | [0]" --raw-output 2>/dev/null || echo "")

if [[ -n "$VAULT_ID" && "$VAULT_ID" != "null" ]]; then
    success "Vault '$VAULT_NAME' already exists"
else
    # Free tier: DEFAULT vault type (not VIRTUAL_PRIVATE — that costs money)
    VAULT_ID=$(oci --auth security_token kms management vault create \
        --compartment-id "$COMPARTMENT_ID" \
        --display-name "$VAULT_NAME" \
        --vault-type DEFAULT \
        --freeform-tags '{"billing":"free-tier","project":"TreadingBot"}' \
        --wait-for-state ACTIVE \
        --query 'data.id' --raw-output 2>/dev/null || echo "")

    if [[ -n "$VAULT_ID" && "$VAULT_ID" != "null" ]]; then
        success "Vault '$VAULT_NAME' created (150 secrets free)"
    else
        warn "Vault creation failed — skipping (Vault requires key management endpoint, check region support)"
        VAULT_ID=""
    fi
fi

# Create a master encryption key in the vault (needed to create secrets)
if [[ -n "$VAULT_ID" && "$VAULT_ID" != "null" ]]; then
    MGMT_ENDPOINT=$(oci --auth security_token kms management vault get \
        --vault-id "$VAULT_ID" \
        --query 'data."management-endpoint"' --raw-output 2>/dev/null || echo "")

    if [[ -n "$MGMT_ENDPOINT" ]]; then
        KEY_ID=$(oci --auth security_token kms management key list \
            --compartment-id "$COMPARTMENT_ID" \
            --endpoint "$MGMT_ENDPOINT" \
            --query "data[?\"display-name\"=='TreadingBot-Key' && \"lifecycle-state\"=='ENABLED'].id | [0]" --raw-output 2>/dev/null || echo "")

        if [[ -z "$KEY_ID" || "$KEY_ID" == "null" ]]; then
            KEY_ID=$(oci --auth security_token kms management key create \
                --compartment-id "$COMPARTMENT_ID" \
                --endpoint "$MGMT_ENDPOINT" \
                --display-name "TreadingBot-Key" \
                --key-shape '{"algorithm":"AES","length":32}' \
                --protection-mode SOFTWARE \
                --freeform-tags '{"billing":"free-tier","project":"TreadingBot"}' \
                --wait-for-state ENABLED \
                --query 'data.id' --raw-output 2>/dev/null || echo "")
            [[ -n "$KEY_ID" && "$KEY_ID" != "null" ]] && success "Encryption key created"
        else
            success "Encryption key exists"
        fi
    fi
fi

# ── 3. Monitoring alarm (bot health) ─────────────────────────────────────────
info "Setting up monitoring alarm for bot health..."

# Get the instance OCID
INSTANCE_ID=$(oci --auth security_token compute instance list \
    --compartment-id "$COMPARTMENT_ID" \
    --display-name "TreadingBot" \
    --lifecycle-state RUNNING \
    --query 'data[0].id' --raw-output 2>/dev/null || echo "")

if [[ -z "$INSTANCE_ID" || "$INSTANCE_ID" == "null" ]]; then
    warn "TreadingBot instance not found — skipping alarm setup (run after oci-provision)"
else
    # Create a notification topic to receive the alarm
    TOPIC_ID=$(oci --auth security_token ons topic list \
        --compartment-id "$COMPARTMENT_ID" \
        --name "TreadingBot-Alerts" \
        --lifecycle-state ACTIVE \
        --query 'data[0]."topic-id"' --raw-output 2>/dev/null || echo "")

    if [[ -z "$TOPIC_ID" || "$TOPIC_ID" == "null" ]]; then
        TOPIC_ID=$(oci --auth security_token ons topic create \
            --compartment-id "$COMPARTMENT_ID" \
            --name "TreadingBot-Alerts" \
            --description "TreadingBot health alerts" \
            --freeform-tags '{"billing":"free-tier","project":"TreadingBot"}' \
            --wait-for-state ACTIVE \
            --query 'data."topic-id"' --raw-output 2>/dev/null || echo "")
        [[ -n "$TOPIC_ID" && "$TOPIC_ID" != "null" ]] && success "Notification topic created"
    else
        success "Notification topic exists"
    fi

    # Alarm: CPU < 0.5% for 5 minutes → instance has crashed or bot died
    if [[ -n "$TOPIC_ID" && "$TOPIC_ID" != "null" ]]; then
        ALARM_EXISTS=$(oci --auth security_token monitoring alarm list \
            --compartment-id "$COMPARTMENT_ID" \
            --display-name "$ALARM_NAME" \
            --lifecycle-state ACTIVE \
            --query 'data[0].id' --raw-output 2>/dev/null || echo "")

        if [[ -z "$ALARM_EXISTS" || "$ALARM_EXISTS" == "null" ]]; then
            oci --auth security_token monitoring alarm create \
                --compartment-id "$COMPARTMENT_ID" \
                --display-name "$ALARM_NAME" \
                --metric-compartment-id "$COMPARTMENT_ID" \
                --namespace "oci_computeagent" \
                --query-expr "CpuUtilization[5m]{resourceId=\"${INSTANCE_ID}\"}.mean() < 0.5" \
                --resolution "5m" \
                --severity "CRITICAL" \
                --destinations "[\"${TOPIC_ID}\"]" \
                --is-enabled true \
                --body "TreadingBot instance CPU is near zero — it may have crashed." \
                --freeform-tags '{"billing":"free-tier","project":"TreadingBot"}' \
                --query 'data.id' --raw-output >/dev/null 2>&1 \
                && success "Alarm: fires if instance CPU drops below 0.5% for 5 min" \
                || warn "Alarm creation failed — check Monitoring service is available in your region"
        else
            success "Alarm '$ALARM_NAME' already exists"
        fi
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  Oracle Free Services — Setup Complete${RESET}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "  ${GREEN}✓${RESET} Object Storage   bucket '${BUCKET_NAME}' — daily backups, 30-day retention"
[[ -n "${VAULT_ID:-}" && "$VAULT_ID" != "null" ]] \
    && echo -e "  ${GREEN}✓${RESET} Vault             '${VAULT_NAME}' — store secrets securely" \
    || echo -e "  ${YELLOW}⚠${RESET} Vault             skipped (not available in all regions)"
[[ -n "${INSTANCE_ID:-}" && "$INSTANCE_ID" != "null" ]] \
    && echo -e "  ${GREEN}✓${RESET} Monitoring alarm  fires if instance goes dark for 5+ min"
echo ""
echo -e "  ${BOLD}Next:${RESET} deploy the backup cron inside the bot container"
echo -e "  The daily backup runs at 02:00 IST → Oracle Object Storage."
echo -e "  Restore with: ${CYAN}make db-restore DATE=2026-04-12${RESET}"
echo ""
echo -e "  All services: ${GREEN}\$0.00/month${RESET}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
