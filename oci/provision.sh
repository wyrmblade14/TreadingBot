#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# TreadingBot — Oracle Cloud Infrastructure provisioning
#
# ALWAYS FREE ONLY — this script will abort rather than create any paid resource.
#
# Free tier limits used:
#   Compute   VM.Standard.A1.Flex — 4 OCPU + 24 GB RAM total (Ampere ARM, always free)
#   Storage   50 GB boot volume   — within the 200 GB block storage free allowance
#   Network   1 VCN, 1 subnet, 1 internet gateway — all free
#   Public IP Ephemeral only      — reserved/static IPs cost money, we don't use them
#
# What this creates:
#   VCN + subnet + internet gateway + route table (all free, idempotent)
#   Security list: SSH (22), dashboard (80), Kite callback (7777) — Tailscale-scoped
#   1× VM.Standard.A1.Flex — 4 OCPU / 24 GB RAM / 50 GB boot (always free)
#   Cloud-init: installs Docker, make, git, Tailscale automatically
#
# Prerequisites (run once on your local machine):
#   pip install oci-cli
#   oci --auth security_token setup config         ← needs tenancy OCID, user OCID, region, API key
#   sudo apt-get install jq  ← or brew install jq on Mac
#
# Usage:
#   make oci-provision
#   make oci-provision ARGS="--compartment-id ocid1.compartment.oc1..xxx"
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info()    { echo -e "${CYAN}▸ $*${RESET}"; }
success() { echo -e "${GREEN}✓ $*${RESET}"; }
warn()    { echo -e "${YELLOW}⚠ $*${RESET}"; }
die()     { echo -e "${RED}✗ $*${RESET}" >&2; exit 1; }

# ── Always-Free limits (hard-coded — do not change) ───────────────────────────
readonly SHAPE="VM.Standard.E2.1.Micro"
readonly MAX_FREE_OCPUS=2          # Oracle allows up to 2 x86 Micro instances free
readonly MAX_FREE_MEM_GB=1         # Oracle allows up to 1 GB per Micro instance free
readonly BOOT_VOLUME_GB=50         # Default minimum; 200 GB free total — 50 GB is safe
readonly OCPUS=1
readonly MEM_GB=1

# ── Other config ──────────────────────────────────────────────────────────────
DISPLAY_NAME="TreadingBot"
OS_NAME="Canonical Ubuntu"
OS_VERSION="22.04"
VCN_CIDR="10.0.0.0/16"
SUBNET_CIDR="10.0.0.0/24"
SSH_KEY="${HOME}/.ssh/id_rsa.pub"
COMPARTMENT_ID=""

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --compartment-id) COMPARTMENT_ID="$2"; shift 2 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}TreadingBot — Oracle Cloud Provisioning (Always Free)${RESET}"
echo -e "Shape: ${CYAN}${SHAPE}${RESET}  OCPUs: ${CYAN}${OCPUS}${RESET}  RAM: ${CYAN}${MEM_GB} GB${RESET}  Boot: ${CYAN}${BOOT_VOLUME_GB} GB${RESET}"
echo -e "${GREEN}No paid resources will be created. Script aborts if anything would cost money.${RESET}"
echo ""

# ── Prerequisites ─────────────────────────────────────────────────────────────
info "Checking prerequisites..."

command -v oci --auth security_token &>/dev/null \
    || die "OCI CLI not found.\n  Install: pip install oci-cli\n  Configure: oci --auth security_token setup config"

command -v jq &>/dev/null \
    || die "jq not found.\n  Install: sudo apt-get install -y jq  OR  brew install jq"

[[ -f "$SSH_KEY" ]] \
    || die "SSH public key not found at $SSH_KEY\n  Run: ssh-keygen -t rsa -b 4096"

# Verify OCI CLI is actually authenticated
oci --auth security_token iam region list --query 'data[0].name' --raw-output &>/dev/null \
    || die "OCI CLI not configured or auth failed.\n  Run: oci --auth security_token setup config"

success "Prerequisites OK"

# ── Compartment ───────────────────────────────────────────────────────────────
if [[ -z "$COMPARTMENT_ID" ]]; then
    info "Resolving compartment (root tenancy)..."
    TENANCY_ID=$(oci --auth security_token iam tenancy get \
        --tenancy-id "$(grep -E '^tenancy\s*=' ~/.oci/config | head -1 | cut -d= -f2 | tr -d ' ')" \
        --query 'data.id' --raw-output 2>/dev/null \
        || grep -E '^tenancy\s*=' ~/.oci/config | head -1 | cut -d= -f2 | tr -d ' ')
    COMPARTMENT_ID="$TENANCY_ID"
fi

[[ -n "$COMPARTMENT_ID" && "$COMPARTMENT_ID" != "null" ]] \
    || die "Could not determine compartment ID.\n  Pass: --compartment-id ocid1.tenancy.oc1..xxx\n  Find it at: cloud.oracle.com → Profile → Tenancy"

success "Compartment: $COMPARTMENT_ID"

# ── Free tier check: existing A1 usage ────────────────────────────────────────
info "Checking existing A1 free-tier usage..."
EXISTING_A1_JSON=$(oci --auth security_token compute instance list \
    --compartment-id "$COMPARTMENT_ID" \
    --shape "$SHAPE" \
    --lifecycle-state RUNNING \
    --query 'data[*].{"name":"display-name","ocpus":"shape-config.ocpus"}' \
    --raw-output 2>/dev/null || echo "[]")

EXISTING_OCPUS=$(echo "$EXISTING_A1_JSON" | jq '[.[].ocpus // 0] | add // 0' 2>/dev/null || echo "0")
EXISTING_COUNT=$(echo "$EXISTING_A1_JSON" | jq 'length' 2>/dev/null || echo "0")

if (( $(echo "$EXISTING_OCPUS + $OCPUS > $MAX_FREE_OCPUS" | bc -l) )); then
    die "Free tier limit would be exceeded.\n" \
        "  Already running: ${EXISTING_COUNT} A1 instance(s) using ${EXISTING_OCPUS} OCPUs\n" \
        "  Requesting: ${OCPUS} more OCPUs\n" \
        "  Free limit: ${MAX_FREE_OCPUS} OCPUs total\n" \
        "  Stop existing instances first, or use --compartment-id with a different compartment."
fi

if [[ "$EXISTING_COUNT" -gt 0 ]]; then
    warn "Existing A1 instances: ${EXISTING_COUNT} (${EXISTING_OCPUS} OCPUs used). Proceeding within free limit."
else
    success "No existing A1 instances — full free tier available"
fi

# ── Availability domain ───────────────────────────────────────────────────────
info "Finding availability domain..."
AD=$(oci --auth security_token iam availability-domain list \
    --compartment-id "$COMPARTMENT_ID" \
    --query 'data[0].name' --raw-output)
[[ -n "$AD" && "$AD" != "null" ]] || die "No availability domains found in this region."
success "Availability domain: $AD"

# ── VCN ───────────────────────────────────────────────────────────────────────
info "Checking VCN..."
VCN_ID=$(oci --auth security_token network vcn list \
    --compartment-id "$COMPARTMENT_ID" \
    --display-name "${DISPLAY_NAME}-VCN" \
    --lifecycle-state AVAILABLE \
    --query 'data[0].id' --raw-output 2>/dev/null || echo "")

if [[ -z "$VCN_ID" || "$VCN_ID" == "null" ]]; then
    # Oracle allows 2 VCNs free — check we're not over
    VCN_COUNT=$(oci --auth security_token network vcn list \
        --compartment-id "$COMPARTMENT_ID" \
        --lifecycle-state AVAILABLE \
        --query 'data | length' --raw-output 2>/dev/null || echo "0")
    (( VCN_COUNT < 2 )) \
        || die "Already have 2 VCNs (free tier limit). Delete one first or reuse an existing VCN."
    info "Creating VCN..."
    VCN_ID=$(oci --auth security_token network vcn create \
        --compartment-id "$COMPARTMENT_ID" \
        --cidr-block "$VCN_CIDR" \
        --display-name "${DISPLAY_NAME}-VCN" \
        --freeform-tags '{"billing":"free-tier","project":"TreadingBot"}' \
        --wait-for-state AVAILABLE \
        --query 'data.id' --raw-output)
    success "VCN created"
else
    success "Reusing VCN"
fi

# ── Internet gateway ──────────────────────────────────────────────────────────
info "Checking internet gateway..."
IGW_ID=$(oci --auth security_token network internet-gateway list \
    --compartment-id "$COMPARTMENT_ID" \
    --vcn-id "$VCN_ID" \
    --lifecycle-state AVAILABLE \
    --query 'data[0].id' --raw-output 2>/dev/null || echo "")

if [[ -z "$IGW_ID" || "$IGW_ID" == "null" ]]; then
    info "Creating internet gateway..."
    IGW_ID=$(oci --auth security_token network internet-gateway create \
        --compartment-id "$COMPARTMENT_ID" \
        --vcn-id "$VCN_ID" \
        --is-enabled true \
        --display-name "${DISPLAY_NAME}-IGW" \
        --freeform-tags '{"billing":"free-tier","project":"TreadingBot"}' \
        --wait-for-state AVAILABLE \
        --query 'data.id' --raw-output)
    success "Internet gateway created"
else
    success "Reusing internet gateway"
fi

# ── Route table ───────────────────────────────────────────────────────────────
info "Updating default route table..."
DEFAULT_RT_ID=$(oci --auth security_token network route-table list \
    --compartment-id "$COMPARTMENT_ID" \
    --vcn-id "$VCN_ID" \
    --lifecycle-state AVAILABLE \
    --query 'data[0].id' --raw-output)

oci --auth security_token network route-table update \
    --rt-id "$DEFAULT_RT_ID" \
    --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"${IGW_ID}\"}]" \
    --force \
    --wait-for-state AVAILABLE \
    --query 'data.id' --raw-output >/dev/null
success "Route table updated"

# ── Security list ─────────────────────────────────────────────────────────────
info "Configuring security list..."
SL_ID=$(oci --auth security_token network security-list list \
    --compartment-id "$COMPARTMENT_ID" \
    --vcn-id "$VCN_ID" \
    --lifecycle-state AVAILABLE \
    --query 'data[0].id' --raw-output)

# Port 22: SSH from anywhere (needed for initial setup; close later once Tailscale is up)
# Port 80: Dashboard — Tailscale subnet only (100.64.0.0/10 is the Tailscale CGNAT range)
# Port 7777: Kite OAuth callback — Tailscale only
# All other inbound: blocked
INGRESS_RULES='[
  {
    "protocol": "6",
    "source": "0.0.0.0/0",
    "tcpOptions": {"destinationPortRange": {"min": 22, "max": 22}},
    "isStateless": false,
    "description": "SSH (close this after Tailscale is set up)"
  },
  {
    "protocol": "6",
    "source": "100.64.0.0/10",
    "tcpOptions": {"destinationPortRange": {"min": 80, "max": 80}},
    "isStateless": false,
    "description": "HTTP dashboard — Tailscale only"
  },
  {
    "protocol": "6",
    "source": "100.64.0.0/10",
    "tcpOptions": {"destinationPortRange": {"min": 7777, "max": 7777}},
    "isStateless": false,
    "description": "Kite OAuth callback — Tailscale only"
  }
]'

oci --auth security_token network security-list update \
    --security-list-id "$SL_ID" \
    --ingress-security-rules "$INGRESS_RULES" \
    --force \
    --wait-for-state AVAILABLE \
    --query 'data.id' --raw-output >/dev/null
success "Security list: SSH(22) open, ports 80+7777 Tailscale-only, everything else blocked"

# ── Subnet ────────────────────────────────────────────────────────────────────
info "Checking subnet..."
SUBNET_ID=$(oci --auth security_token network subnet list \
    --compartment-id "$COMPARTMENT_ID" \
    --vcn-id "$VCN_ID" \
    --display-name "${DISPLAY_NAME}-Subnet" \
    --lifecycle-state AVAILABLE \
    --query 'data[0].id' --raw-output 2>/dev/null || echo "")

if [[ -z "$SUBNET_ID" || "$SUBNET_ID" == "null" ]]; then
    info "Creating subnet..."
    SUBNET_ID=$(oci --auth security_token network subnet create \
        --compartment-id "$COMPARTMENT_ID" \
        --vcn-id "$VCN_ID" \
        --cidr-block "$SUBNET_CIDR" \
        --availability-domain "$AD" \
        --display-name "${DISPLAY_NAME}-Subnet" \
        --security-list-ids "[\"${SL_ID}\"]" \
        --route-table-id "$DEFAULT_RT_ID" \
        --freeform-tags '{"billing":"free-tier","project":"TreadingBot"}' \
        --wait-for-state AVAILABLE \
        --query 'data.id' --raw-output)
    success "Subnet created"
else
    success "Reusing subnet"
fi

# ── Image: Ubuntu 22.04 ARM ───────────────────────────────────────────────────
info "Finding latest Ubuntu 22.04 ARM image..."
IMAGE_ID=$(oci --auth security_token compute image list \
    --compartment-id "$COMPARTMENT_ID" \
    --operating-system "$OS_NAME" \
    --operating-system-version "$OS_VERSION" \
    --shape "$SHAPE" \
    --sort-by TIMECREATED \
    --sort-order DESC \
    --query 'data[0].id' --raw-output 2>/dev/null || echo "")

[[ -n "$IMAGE_ID" && "$IMAGE_ID" != "null" ]] \
    || die "Ubuntu 22.04 ARM image not found in this region.\n  Check available images: oci --auth security_token compute image list --compartment-id $COMPARTMENT_ID"
success "Image: Ubuntu 22.04 ARM"

# ── Block volume pre-check ────────────────────────────────────────────────────
info "Checking block volume free-tier usage..."
TOTAL_BV_GB=$(oci --auth security_token bv volume list \
    --compartment-id "$COMPARTMENT_ID" \
    --lifecycle-state AVAILABLE \
    --query 'data[*]."size-in-gbs" | [0]' --raw-output 2>/dev/null || echo "0")
# Boot volumes are separate; just warn if approaching 200 GB
EXISTING_BV_GB=$(oci --auth security_token bv boot-volume list \
    --compartment-id "$COMPARTMENT_ID" \
    --availability-domain "$AD" \
    --query '[data[*]."size-in-gbs"] | [0] | add // 0' --raw-output 2>/dev/null || echo "0")

PROJECTED_TOTAL=$(( ${EXISTING_BV_GB:-0} + BOOT_VOLUME_GB ))
if (( PROJECTED_TOTAL > 200 )); then
    die "Block storage would exceed 200 GB free limit.\n" \
        "  Existing boot volumes: ${EXISTING_BV_GB} GB\n" \
        "  New boot volume: ${BOOT_VOLUME_GB} GB\n" \
        "  Projected total: ${PROJECTED_TOTAL} GB (limit: 200 GB)\n" \
        "  Delete unused volumes first."
fi
success "Block storage OK (${EXISTING_BV_GB} GB existing + ${BOOT_VOLUME_GB} GB new = ${PROJECTED_TOTAL}/200 GB)"

# ── Cloud-init ────────────────────────────────────────────────────────────────
CLOUD_INIT_SCRIPT=$(cat <<'ENDINIT'
#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get upgrade -y -qq

# Docker (official script — always installs latest stable)
curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu
apt-get install -y docker-compose-plugin make git nano jq bc

# Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# Oracle iptables fix: allow Docker bridge forwarding (blocked by default on OCI)
iptables  -I FORWARD -j ACCEPT
ip6tables -I FORWARD -j ACCEPT
iptables  -I INPUT -m state --state RELATED,ESTABLISHED -j ACCEPT
apt-get install -y iptables-persistent netfilter-persistent
netfilter-persistent save

# Also persist via cloud-init rc.local for reboots
cat > /etc/rc.local <<'EOF'
#!/bin/bash
iptables  -I FORWARD -j ACCEPT
ip6tables -I FORWARD -j ACCEPT
exit 0
EOF
chmod +x /etc/rc.local

# Done
echo "" >> /etc/motd
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >> /etc/motd
echo "  TreadingBot instance ready" >> /etc/motd
echo "  Next: sudo tailscale up" >> /etc/motd
echo "        git clone <your-repo>" >> /etc/motd
echo "        cd TreadingBot && cp .env.example .env" >> /etc/motd
echo "        nano .env && make up" >> /etc/motd
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >> /etc/motd
touch /var/lib/cloud/instance/treadingbot-ready
ENDINIT
)

CLOUD_INIT_B64=$(echo "$CLOUD_INIT_SCRIPT" | base64 -w 0)

# ── Check if instance already exists ─────────────────────────────────────────
info "Checking for existing TreadingBot instance..."
INSTANCE_ID=$(oci --auth security_token compute instance list \
    --compartment-id "$COMPARTMENT_ID" \
    --display-name "$DISPLAY_NAME" \
    --lifecycle-state RUNNING \
    --query 'data[0].id' --raw-output 2>/dev/null || echo "")

if [[ -n "$INSTANCE_ID" && "$INSTANCE_ID" != "null" ]]; then
    warn "Instance already exists — skipping launch (idempotent)."
else
    # ── Final free-tier confirmation ──────────────────────────────────────────
    echo ""
    echo -e "${BOLD}About to create:${RESET}"
    echo -e "  Shape       ${CYAN}${SHAPE}${RESET}"
    echo -e "  OCPUs       ${CYAN}${OCPUS}${RESET} (free tier max: ${MAX_FREE_OCPUS})"
    echo -e "  RAM         ${CYAN}${MEM_GB} GB${RESET} (free tier max: ${MAX_FREE_MEM_GB} GB)"
    echo -e "  Boot volume ${CYAN}${BOOT_VOLUME_GB} GB${RESET} (free tier max: 200 GB total)"
    echo -e "  Public IP   ${CYAN}ephemeral${RESET} (free — not reserved)"
    echo -e "  Cost        ${GREEN}$0.00 / month${RESET}"
    echo ""
    read -r -p "Proceed? [y/N] " CONFIRM
    [[ "${CONFIRM,,}" == "y" ]] || { echo "Aborted."; exit 0; }

    info "Launching instance (this takes ~2 minutes)..."
    # Create temp file for user-data
    USER_DATA_FILE=$(mktemp)
    echo "$CLOUD_INIT_SCRIPT" > "$USER_DATA_FILE"

    INSTANCE_ID=$(oci --auth security_token compute instance launch \
        --compartment-id  "$COMPARTMENT_ID" \
        --availability-domain "$AD" \
        --shape           "$SHAPE" \
        --image-id        "$IMAGE_ID" \
        --subnet-id       "$SUBNET_ID" \
        --display-name    "$DISPLAY_NAME" \
        --boot-volume-size-in-gbs "$BOOT_VOLUME_GB" \
        --assign-public-ip true \
        --ssh-authorized-keys-file "$SSH_KEY" \
        --user-data-file  "$USER_DATA_FILE" \
        --freeform-tags   '{"billing":"free-tier","project":"TreadingBot"}' \
        --wait-for-state  RUNNING \
        --query 'data.id' --raw-output)

    rm "$USER_DATA_FILE"
    success "Instance running: $INSTANCE_ID"
fi
# ── Get public IP ─────────────────────────────────────────────────────────────
info "Fetching public IP..."
sleep 3
PUBLIC_IP=$(oci --auth security_token compute instance list-vnics \
    --instance-id "$INSTANCE_ID" \
    --query 'data[0]."public-ip"' --raw-output 2>/dev/null || echo "")

[[ -z "$PUBLIC_IP" || "$PUBLIC_IP" == "null" ]] && PUBLIC_IP="<pending — check OCI console>"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  Done. Always Free. \$0.00/month.${RESET}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "  Public IP   ${CYAN}${PUBLIC_IP}${RESET}"
echo -e "  Instance    ${CYAN}${INSTANCE_ID}${RESET}"
echo ""
echo -e "${BOLD}  Cloud-init is running in the background (~3 min).${RESET}"
echo -e "  It installs Docker, make, git, Tailscale automatically."
echo ""
echo -e "${BOLD}  NEXT STEPS:${RESET}"
echo ""
echo -e "  1. SSH in:"
echo -e "       ${YELLOW}ssh ubuntu@${PUBLIC_IP}${RESET}"
echo ""
echo -e "  2. Activate Tailscale (one-time):"
echo -e "       ${YELLOW}sudo tailscale up${RESET}"
echo -e "       Open the printed URL in your browser to approve."
echo -e "       Then note your Tailscale IP:  ${YELLOW}tailscale ip -4${RESET}"
echo ""
echo -e "  3. Clone and configure:"
echo -e "       ${YELLOW}git clone https://github.com/<you>/TreadingBot.git${RESET}"
echo -e "       ${YELLOW}cd TreadingBot${RESET}"
echo -e "       ${YELLOW}cp .env.example .env && nano .env${RESET}"
echo -e "       Set: NEXT_PUBLIC_DASHBOARD_API_URL=http://\$(tailscale ip -4):8000"
echo ""
echo -e "  4. Deploy:"
echo -e "       ${YELLOW}make up${RESET}"
echo ""
echo -e "  5. Set Kite Redirect URL in https://developers.kite.trade:"
echo -e "       ${YELLOW}http://\$(tailscale ip -4):7777${RESET}"
echo ""
echo -e "  After setup, close SSH port 22 in OCI Console → VCN Security List."
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
