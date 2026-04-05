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
#
# Flags:
#   --force   Kill any running instance and restart fresh.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── AMD / software-rendering env vars (must be first — inherited by ALL children)
# Set these before ANY process starts so Wine, Xvfb, and the bridge all see them.
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=softpipe
export MESA_GL_VERSION_OVERRIDE=3.3
export MESA_LOADER_DRIVER_OVERRIDE=softpipe
export WINEDLLOVERRIDES="winevulkan=d;vulkan-1=d"

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

# ── Lock file (prevents multiple simultaneous stack instances) ────────────────
LOCK_FILE="/tmp/trading_bot_$(whoami).lock"
FORCE=0
for arg in "$@"; do
    [[ "$arg" == "--force" ]] && FORCE=1
done

kill_existing_stack() {
    print_warn "Stopping any running trading stack processes..."
    # Kill in reverse dependency order: bot → bridge → MT5 → watchdog
    pkill -TERM -f "real_bot.py"     2>/dev/null || true
    pkill -TERM -f "mt5linux"        2>/dev/null || true
    pkill -TERM -f "terminal64.exe"  2>/dev/null || true
    pkill -TERM -f "watchdog.py"     2>/dev/null || true
    pkill -TERM -f "streamlit.*dashboard" 2>/dev/null || true
    sleep 3
    # Force-kill anything still alive (including all wine/wineserver processes)
    pkill -KILL -f "real_bot.py"     2>/dev/null || true
    pkill -KILL -f "mt5linux"        2>/dev/null || true
    pkill -KILL -f "terminal64.exe"  2>/dev/null || true
    pkill -KILL -f "watchdog.py"     2>/dev/null || true
    pkill -KILL -f "streamlit"       2>/dev/null || true
    pkill -KILL -f "wine"            2>/dev/null || true
    pkill -KILL    "wineserver"      2>/dev/null || true
    # Kill any stale Xvfb on :99
    pkill -KILL -f "Xvfb :99"        2>/dev/null || true
    rm -f "/tmp/.X99-lock" "/tmp/.X11-unix/X99" 2>/dev/null || true
    rm -f "/tmp/trading_watchdog.lock"           2>/dev/null || true
    sleep 2
    print_ok "Existing stack stopped."
}

if [ -f "$LOCK_FILE" ]; then
    OLD_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        if [ "$FORCE" -eq 1 ]; then
            print_warn "Existing instance found (PID $OLD_PID). --force: killing it."
            kill_existing_stack
            kill "$OLD_PID" 2>/dev/null || true
            rm -f "$LOCK_FILE"
        else
            print_err "Trading stack is already running (start.sh PID $OLD_PID)."
            print_err "Use --force to kill it and restart:  $0 --force"
            exit 1
        fi
    else
        print_warn "Stale lock file found (PID ${OLD_PID:-unknown} not running). Cleaning up..."
        kill_existing_stack
        rm -f "$LOCK_FILE"
    fi
fi

# Write this script's PID as the lock
echo $$ > "$LOCK_FILE"

# Xvfb is now managed entirely by watchdog.py (monitored + auto-restarted).
# Export VIRT_DISPLAY so watchdog knows which display number to use.
VIRT_DISPLAY=":99"
export VIRT_DISPLAY

cleanup() {
    rm -f "$LOCK_FILE"
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

# Xvfb check (watchdog starts and monitors Xvfb; warn if missing)
if ! command -v Xvfb &>/dev/null; then
    print_warn "Xvfb not found — install it: sudo pacman -S xorg-server-xvfb"
fi

# Check at least one model exists
MODEL_COUNT=$(ls "$SCRIPT_DIR"/*_model.pkl 2>/dev/null | wc -l)
if [ "$MODEL_COUNT" -eq 0 ]; then
    print_warn "No *_model.pkl files found. Run train_model.py before trading."
fi

if [ "$ERRORS" -gt 0 ]; then
    print_err "Aborting due to the errors above."
    rm -f "$LOCK_FILE"
    exit 1
fi

# ── Create log directory ──────────────────────────────────────────────────────
mkdir -p "$SCRIPT_DIR/logs"

# ── Summary ───────────────────────────────────────────────────────────────────
print_ok "Pre-flight checks passed"
echo ""
echo -e "  Components managed by watchdog (auto-restarted on crash):"
echo -e "    ${CYAN}1${RESET}  Xvfb             (virtual display ${VIRT_DISPLAY}, software GL)"
echo -e "    ${CYAN}2${RESET}  mt5linux bridge  (Wine Python, port 18812 — starts MT5 internally)"
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
"$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/watchdog.py"
