#!/bin/bash
# One-shot setup for ghealth + Fitbit Air stats tooling.
# Safe to re-run: every step checks current state first.
set -euo pipefail
cd "$(dirname "$0")"

BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; CYAN="\033[36m"; RESET="\033[0m"
ok()   { echo -e "  ${GREEN}✓${RESET} $1"; }
warn() { echo -e "  ${YELLOW}!${RESET} $1"; }
err()  { echo -e "  ${RED}✗${RESET} $1"; }
step() { echo -e "\n${BOLD}${CYAN}$1${RESET}"; }

# ---------------------------------------------------------------------------
step "[1/6] Checking prerequisites"

if ! command -v go >/dev/null 2>&1; then
    err "Go is not installed. Install it: https://go.dev/dl/ (or 'brew install go')"
    exit 1
fi
ok "Go found ($(go version | awk '{print $3}'))"

if ! command -v python3 >/dev/null 2>&1; then
    err "python3 is not installed. Install it (e.g. 'brew install python3')."
    exit 1
fi
ok "python3 found ($(python3 --version))"

if ! command -v pip3 >/dev/null 2>&1; then
    err "pip3 is not installed."
    exit 1
fi
ok "pip3 found"

# ---------------------------------------------------------------------------
step "[2/6] Building ghealth"

if [ -x ./ghealth ]; then
    ok "ghealth binary already built"
else
    go build -o ghealth .
    ok "Built ./ghealth"
fi

# ---------------------------------------------------------------------------
step "[3/6] Installing Python dependencies (plotext)"

pip3 install --user -q -r requirements.txt
ok "plotext installed"

# ---------------------------------------------------------------------------
step "[4/6] Google Cloud / OAuth setup"

if ./ghealth auth status >/dev/null 2>&1; then
    ok "Already authenticated with the Google Health API"
else
    echo
    echo "  This needs a one-time Google Cloud project + OAuth client. If you"
    echo "  haven't done this yet:"
    echo
    echo "   1. https://console.cloud.google.com/projectcreate  -- create a project"
    echo "   2. APIs & Services -> Library -> enable 'Google Health API'"
    echo "   3. APIs & Services -> OAuth consent screen -> External -> add yourself"
    echo "      as a Test user, then Data Access -> add all 'Google Health API' scopes"
    echo "   4. APIs & Services -> Credentials -> Create OAuth client ID"
    echo "      -> Application type: Desktop app -> download the JSON"
    echo
    read -rp "  GCP project ID: " GCP_PROJECT_ID
    read -rp "  Path to downloaded client_secret JSON: " CLIENT_SECRET_PATH
    CLIENT_SECRET_PATH="${CLIENT_SECRET_PATH/#\~/$HOME}"

    if [ ! -f "$CLIENT_SECRET_PATH" ]; then
        err "File not found: $CLIENT_SECRET_PATH"
        exit 1
    fi

    ./ghealth setup --project-id "$GCP_PROJECT_ID" --client-secret "$CLIENT_SECRET_PATH"
    ok "Authenticated"

    echo
    warn "IMPORTANT: while your OAuth client is in 'Testing' mode, refresh tokens"
    warn "expire every 7 days. To fix permanently: GCP Console -> OAuth consent"
    warn "screen -> Audience -> Publish App (stays unverified, no review needed"
    warn "for personal use)."
fi

# ---------------------------------------------------------------------------
step "[5/6] Shell alias"

REPO_DIR="$(pwd)"
SHELL_RC="$HOME/.zshrc"
[ -n "${ZDOTDIR:-}" ] && SHELL_RC="$ZDOTDIR/.zshrc"

if grep -q "^fitbit()" "$SHELL_RC" 2>/dev/null; then
    ok "'fitbit' function already present in $SHELL_RC"
else
    cat >> "$SHELL_RC" << EOF

# Fitbit Air stats via ghealth
fitbit() {
  (cd "$REPO_DIR" && python3 stats.py "\$@")
}
EOF
    ok "Added 'fitbit' function to $SHELL_RC (run 'source $SHELL_RC' or open a new terminal)"
fi

# ---------------------------------------------------------------------------
step "[6/6] Token keepalive cron job"

CRON_LINE="0 9 * * * $REPO_DIR/keepalive.sh >> $REPO_DIR/keepalive.log 2>&1"
if crontab -l 2>/dev/null | grep -qF "$REPO_DIR/keepalive.sh"; then
    ok "Keepalive cron job already installed"
else
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    ok "Installed daily keepalive cron job (9am)"
fi

# ---------------------------------------------------------------------------
echo -e "\n${BOLD}${GREEN}Setup complete.${RESET}"
echo -e "  Run: ${BOLD}fitbit${RESET} (open a new terminal, or 'source $SHELL_RC' first)\n"
