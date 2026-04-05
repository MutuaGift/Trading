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

# ── Xvfb virtual display ──────────────────────────────────────────────────────
# MT5 runs under Wine and needs a display. We start a private Xvfb instance on
# :99 so no visible window ever appears on the real desktop (or when headless).
VIRT_DISPLAY_NUM=99
VIRT_DISPLAY=":${VIRT_DISPLAY_NUM}"
XVFB_PID=""

start_xvfb() {
    # Install Xvfb if missing (Arch Linux)
    if ! command -v Xvfb &>/dev/null; then
        print_warn "Xvfb not found. Installing xorg-server-xvfb via pacman…"
        sudo pacman -S --noconfirm xorg-server-xvfb
    fi

    # Kill any stale Xvfb on :99
    pkill -f "Xvfb ${VIRT_DISPLAY}" 2>/dev/null || true
    rm -f "/tmp/.X${VIRT_DISPLAY_NUM}-lock" "/tmp/.X11-unix/X${VIRT_DISPLAY_NUM}" 2>/dev/null || true

    Xvfb "${VIRT_DISPLAY}" -screen 0 1024x768x24 +extension GLX -nolisten tcp &>/dev/null &
    XVFB_PID=$!

    # Wait up to 3 seconds for the display to be ready
    local waited=0
    until xdpyinfo -display "${VIRT_DISPLAY}" &>/dev/null || [ $waited -ge 3 ]; do
        sleep 0.5
        waited=$((waited + 1))
    done

    # Software rendering: avoid GPU/Vulkan/DRI3 errors under Xvfb
    export LIBGL_ALWAYS_SOFTWARE=1
    export GALLIUM_DRIVER=softpipe
    export MESA_GL_VERSION_OVERRIDE=3.3
    # Disable Wine's Vulkan layer entirely (no physical GPU under Xvfb)
    export WINEDLLOVERRIDES="winevulkan=d;vulkan-1=d"

    print_ok "Xvfb started on ${VIRT_DISPLAY} (PID ${XVFB_PID}) — MT5 runs headlessly"
    export VIRT_DISPLAY
}

cleanup() {
    if [ -n "$XVFB_PID" ]; then
        kill "$XVFB_PID" 2>/dev/null || true
        wait "$XVFB_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

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

# Xvfb check (non-fatal here; start_xvfb will install it below)
if ! command -v Xvfb &>/dev/null; then
    print_warn "Xvfb not found — will attempt to install automatically."
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

# ── Start Xvfb virtual display ────────────────────────────────────────────────
start_xvfb

# ── Summary ───────────────────────────────────────────────────────────────────
print_ok "Pre-flight checks passed"
echo ""
echo -e "  Components managed by watchdog:"
echo -e "    ${CYAN}1${RESET}  MetaTrader 5     (Wine, headless on ${VIRT_DISPLAY})"
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

# ── Launch the Python watchdog ────────────────────────────────────────────────
# Run as a child (not exec) so the EXIT trap above can kill Xvfb on the way out.
"$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/watchdog.py"
