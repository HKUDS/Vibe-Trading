#!/usr/bin/env bash
# One-shot bootstrap for the ISOLATED Vibe-Trading VM (VIBE LAB).
# Run as root on a FRESH Ubuntu 24.04 Hetzner VM — never on OLIMPO's box.
#
#   curl -fsSL https://raw.githubusercontent.com/Alexanderr003/Vibe-Trading/claude/vibe-trading-setup-w0m9fg/scripts/vm_bootstrap.sh | bash
#
# After it finishes: add the GitHub Secrets listed at the end, then run the
# "VIBE LAB deploy" workflow (deploys the app via docker compose).
set -euo pipefail

BRANCH="claude/vibe-trading-setup-w0m9fg"
REPO_URL="https://github.com/Alexanderr003/Vibe-Trading.git"
DEPLOY_USER="vibe"

[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }

# Refuse to run on OLIMPO's machine (isolation invariant I-V1).
if ip -4 addr show 2>/dev/null | grep -q "167.233.46.18"; then
  echo "FATAL: this looks like OLIMPO's box (167.233.46.18). Aborting (I-V1)."
  exit 1
fi

echo "==> System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -yq docker.io docker-compose-v2 ufw git curl

echo "==> Deploy user '${DEPLOY_USER}'"
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$DEPLOY_USER"
fi
usermod -aG docker "$DEPLOY_USER"

# Same SSH key that reached root must work for the deploy user.
if [ -f /root/.ssh/authorized_keys ]; then
  install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
  install -m 600 -o "$DEPLOY_USER" -g "$DEPLOY_USER" \
    /root/.ssh/authorized_keys "/home/$DEPLOY_USER/.ssh/authorized_keys"
fi

echo "==> Firewall: deny incoming, allow SSH only"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

echo "==> Clone repo as ${DEPLOY_USER} (branch: ${BRANCH})"
su - "$DEPLOY_USER" -c "
  set -euo pipefail
  if [ ! -d ~/Vibe-Trading/.git ]; then
    git clone '$REPO_URL' ~/Vibe-Trading
  fi
  cd ~/Vibe-Trading
  git fetch origin '$BRANCH'
  git checkout -B '$BRANCH' 'origin/$BRANCH'
"

echo
echo "==> Bootstrap DONE. Next steps (owner):"
echo "  1. In github.com/Alexanderr003/Vibe-Trading → Settings → Secrets and"
echo "     variables → Actions, add:"
echo "       VIBE_SSH_HOST      = this VM's IP"
echo "       VIBE_SSH_USER      = ${DEPLOY_USER}"
echo "       VIBE_SSH_KEY       = private key matching the authorized key above"
echo "       OPENROUTER_API_KEY = LLM key created FOR THIS PROJECT (never OLIMPO's)"
echo "  2. Run the 'VIBE LAB deploy' workflow (Actions tab, branch ${BRANCH})."
echo "     It writes agent/.env from the secrets and runs docker compose."
