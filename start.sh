#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start.sh  –  Single-command launcher for the full AI trading bot stack.
#
# Starts (via watchdog.py):
#   1. MetaTrader 5      (Wine)
#   2. mt5linux bridge   (Wine Python)
#   3. real_bot.py       (AI trading loop)
#   4. dashboard.py      (Streamlit UI  →  http://localhost:8501)
#
# The watchdog monitors all four processes and restarts any that crash.
# Press Ctrl-C here to shut everything down cleanly.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# Resolve the directory containing this script regardless of where it is called from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colour helpers (graceful fallback if terminal has no colour support) ─────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
print_header() { echo -e "${BOLD}${CYAN}$1${RESET}"; }
print_ok()     { echo -e "  ${GREEN}✔${RESET}  $1"; }
print_warn()   { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
print_err()    { echo -e "  ${RED}✖${RESET}  $1"; }

# ── Pre-flight checks ─────────────────────────────────────────────────────────
print_header ""
print_header "  AI Trading Bot — Full Stack Launcher"
print_header ""

ERRORS=0

if [ ! -f "$SCRIPT_DIR/venv/bin/python" ]; then
    print_err "Python venv not found at ./venv/"
    print_err "Create it with:"
    print_err "    python -m venv venv"
    print_err "    ./venv/bin/pip install -r requirements.txt"
    ERRORS=1
fi

if [ ! -f "$SCRIPT_DIR/watchdog.py" ]; then
    print_err "watchdog.py not found in $SCRIPT_DIR"
    ERRORS=1
fi

if [ ! -f "$SCRIPT_DIR/real_bot.py" ]; then
    print_err "real_bot.py not found in $SCRIPT_DIR"
    ERRORS=1
fi

if ! command -v wine &>/dev/null; then
    print_warn "wine not found in PATH — MT5 and the bridge will fail to start."
fi

# Check at least one model exists
MODEL_COUNT=$(ls "$SCRIPT_DIR"/*_model.pkl 2>/dev/null | wc -l)
if [ "$MODEL_COUNT" -eq 0 ]; then
    print_warn "No *_model.pkl files found. Run train_model.py before trading."
fi

if [ "$ERRORS" -gt 0 ]; then
    print_err "Aborting due to the errors above."
    exit 1
fi

# ── Create log directory ──────────────────────────────────────────────────────
mkdir -p "$SCRIPT_DIR/logs"

# ── Summary ───────────────────────────────────────────────────────────────────
print_ok "Pre-flight checks passed"
echo ""
echo -e "  Components managed by watchdog:"
echo -e "    ${CYAN}1${RESET}  MetaTrader 5     (Wine)"
echo -e "    ${CYAN}2${RESET}  mt5linux bridge  (Wine Python)"
echo -e "    ${CYAN}3${RESET}  real_bot.py      (AI trading loop)"
echo -e "    ${CYAN}4${RESET}  dashboard.py     (Streamlit UI)"
echo ""
echo -e "  Dashboard  →  ${BOLD}http://localhost:8501${RESET}"
echo -e "  Logs       →  ${BOLD}$SCRIPT_DIR/logs/${RESET}"
echo ""
echo -e "  ${YELLOW}Press Ctrl-C to stop everything cleanly.${RESET}"
echo ""
print_header "─────────────────────────────────────────────────────"
echo ""

# ── Hand off to the Python watchdog ──────────────────────────────────────────
# 'exec' replaces this shell process with Python so that signals (Ctrl-C)
# go directly to the watchdog, which shuts all children down cleanly.
exec "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/watchdog.py"
