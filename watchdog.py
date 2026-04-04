"""
watchdog.py – Starts and monitors every component of the trading stack.

Components managed
──────────────────
  1. MetaTrader 5   (Wine)
  2. mt5linux bridge (Wine Python)
  3. real_bot.py    (AI trading loop)
  4. dashboard.py   (Streamlit UI)

Behaviour
─────────
• Starts all components in the correct order with startup delays.
• Polls every POLL_INTERVAL seconds; restarts any process that has died.
• Uses exponential back-off (capped at MAX_BACKOFF seconds) so a
  repeatedly-crashing component does not spin in a restart storm.
• Back-off counter resets if the process stays alive for STABLE_UPTIME seconds.
• Writes its own log to logs/watchdog.log and to stdout.
• Shuts everything down cleanly on SIGINT / SIGTERM (Ctrl-C).
"""

import os
import sys
import signal
import subprocess
import time
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
LOG_DIR    = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

VENV_PYTHON    = str(SCRIPT_DIR / "venv" / "bin" / "python")
VENV_STREAMLIT = str(SCRIPT_DIR / "venv" / "bin" / "streamlit")

# ── Watchdog tunables ─────────────────────────────────────────────────────────
POLL_INTERVAL  = 30    # Seconds between liveness checks
STABLE_UPTIME  = 600   # Seconds running without crash → reset back-off counter
MAX_BACKOFF    = 300   # Cap on restart delay (5 minutes)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(message)s",
    handlers=[
        RotatingFileHandler(
            LOG_DIR / "watchdog.log", maxBytes=5_000_000, backupCount=5
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("watchdog")

# ── Component definitions ─────────────────────────────────────────────────────
# Each entry:
#   cmd           – list passed to Popen (no shell=True)
#   startup_delay – seconds to wait *after* this process starts before
#                   launching the next one
#   use_display   – inject DISPLAY=:0 (needed for Wine / Wine-based apps)
#   log_file      – stdout + stderr of the subprocess are appended here

DISPLAY = os.environ.get("DISPLAY", ":0")

COMPONENTS: dict = {
    "mt5": {
        "cmd":           ["wine", "C:/Program Files/MetaTrader 5/terminal64.exe"],
        "startup_delay": 15,
        "use_display":   True,
        "log_file":      LOG_DIR / "mt5.log",
    },
    "bridge": {
        "cmd":           ["wine", "python", "-m", "mt5linux"],
        "startup_delay": 10,
        "use_display":   True,
        "log_file":      LOG_DIR / "bridge.log",
    },
    "bot": {
        "cmd":           [VENV_PYTHON, str(SCRIPT_DIR / "real_bot.py")],
        "startup_delay": 5,
        "use_display":   False,
        "log_file":      LOG_DIR / "bot_process.log",
    },
    "dashboard": {
        "cmd":           [
            VENV_STREAMLIT, "run", str(SCRIPT_DIR / "dashboard.py"),
            "--server.headless", "true",
        ],
        "startup_delay": 3,
        "use_display":   False,
        "log_file":      LOG_DIR / "dashboard.log",
    },
}

# ── Runtime state ─────────────────────────────────────────────────────────────
processes: dict        = {}   # name → subprocess.Popen
restart_counts: dict   = {}   # name → int
last_crash_time: dict  = {}   # name → float (time.time())
start_time: dict       = {}   # name → float (time.time())

_shutting_down = False


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def build_env(use_display: bool) -> dict:
    env = os.environ.copy()
    if use_display:
        env["DISPLAY"] = DISPLAY
    return env


def restart_delay(name: str) -> float:
    """Exponential back-off: 30s → 60s → 120s → … → MAX_BACKOFF."""
    count = restart_counts.get(name, 0)
    return min(30 * (2 ** count), MAX_BACKOFF)


def launch(name: str, wait_after: bool = True) -> subprocess.Popen:
    """Start a component, append its output to its log file, return the Popen."""
    cfg = COMPONENTS[name]
    log_path = cfg["log_file"]
    env = build_env(cfg["use_display"])

    logger.info(f"Starting [{name}]: {' '.join(str(c) for c in cfg['cmd'])}")

    log_fh = open(log_path, "a")
    proc = subprocess.Popen(
        cfg["cmd"],
        stdout=log_fh,
        stderr=log_fh,
        env=env,
        cwd=str(SCRIPT_DIR),
    )
    log_fh.close()  # Safe: child process holds its own fd copy

    processes[name]   = proc
    start_time[name]  = time.time()

    if wait_after:
        delay = cfg["startup_delay"]
        logger.info(f"  Waiting {delay}s for [{name}] to initialise…")
        time.sleep(delay)

    return proc


# ═════════════════════════════════════════════════════════════════════════════
# Shutdown handler
# ═════════════════════════════════════════════════════════════════════════════

def shutdown_all(signum=None, frame=None) -> None:
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True

    logger.info("Shutdown signal received. Stopping all components…")

    # Terminate in reverse start order
    for name in reversed(list(COMPONENTS.keys())):
        proc = processes.get(name)
        if proc and proc.poll() is None:
            logger.info(f"  Terminating [{name}] (PID {proc.pid})…")
            proc.terminate()

    # Give processes 5 seconds to exit gracefully
    time.sleep(5)

    # Force-kill anything still alive
    for name, proc in processes.items():
        if proc and proc.poll() is None:
            logger.info(f"  Force-killing [{name}] (PID {proc.pid})")
            proc.kill()

    logger.info("All components stopped. Goodbye.")
    sys.exit(0)


signal.signal(signal.SIGINT,  shutdown_all)
signal.signal(signal.SIGTERM, shutdown_all)


# ═════════════════════════════════════════════════════════════════════════════
# Start-up sequence
# ═════════════════════════════════════════════════════════════════════════════

logger.info("=" * 60)
logger.info("  Trading Bot Watchdog starting")
logger.info(f"  Script dir : {SCRIPT_DIR}")
logger.info(f"  Log dir    : {LOG_DIR}")
logger.info(f"  Dashboard  : http://localhost:8501")
logger.info("=" * 60)

for component_name in ["mt5", "bridge", "bot", "dashboard"]:
    try:
        launch(component_name, wait_after=True)
        logger.info(f"  [{component_name}] started (PID {processes[component_name].pid})")
    except Exception as exc:
        logger.error(f"  Failed to start [{component_name}]: {exc}")

logger.info("All components started. Watchdog monitoring loop active.")
logger.info(f"Checking every {POLL_INTERVAL}s. Press Ctrl-C to stop everything.\n")


# ═════════════════════════════════════════════════════════════════════════════
# Monitoring loop
# ═════════════════════════════════════════════════════════════════════════════

while not _shutting_down:
    time.sleep(POLL_INTERVAL)

    if _shutting_down:
        break

    for name, proc in list(processes.items()):
        if proc is None:
            continue

        exit_code = proc.poll()
        if exit_code is None:
            # Still alive — check if we can reset its back-off counter
            uptime = time.time() - start_time.get(name, time.time())
            if uptime >= STABLE_UPTIME and restart_counts.get(name, 0) > 0:
                logger.info(
                    f"[{name}] stable for {STABLE_UPTIME}s — resetting back-off counter."
                )
                restart_counts[name] = 0
            continue

        # Process has exited
        count = restart_counts.get(name, 0)
        delay = restart_delay(name)

        logger.warning(
            f"[{name}] exited (code={exit_code}). "
            f"Restart #{count + 1} in {delay:.0f}s…"
        )
        last_crash_time[name] = time.time()

        time.sleep(delay)

        if _shutting_down:
            break

        restart_counts[name] = count + 1
        try:
            launch(name, wait_after=False)
            logger.info(
                f"[{name}] restarted (PID {processes[name].pid}, "
                f"attempt #{restart_counts[name]})"
            )
        except Exception as exc:
            logger.error(f"Failed to restart [{name}]: {exc}")
