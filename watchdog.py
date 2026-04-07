"""
watchdog.py – Starts and monitors every component of the trading stack on Windows.

Components managed
──────────────────
  1. real_bot.py       (AI trading loop — connects to MT5 natively)
  2. dashboard.py      (Streamlit UI)

MetaTrader 5 is NOT launched here; the native MetaTrader5 Python library
(mt5.initialize) starts and manages terminal64.exe directly.

Behaviour
─────────
• Starts all components in the correct order with startup delays.
• Polls every POLL_INTERVAL seconds; restarts any process that has died.
• Uses exponential back-off (capped at MAX_BACKOFF seconds) so a
  repeatedly-crashing component does not spin in a restart storm.
• Back-off resets if the process stays alive for STABLE_UPTIME seconds.
• Writes its own log to logs/watchdog.log and to stdout.
• Shuts everything down cleanly on Ctrl-C (SIGINT).
"""

import os
import sys
import signal
import subprocess
import time
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler


if __name__ == "__main__":

    # ── Single-instance guard ─────────────────────────────────────────────────
    # Write our PID to a lock file; if another watchdog is running (PID exists)
    # exit immediately.  Uses os.kill(pid, 0) which works on Windows.
    _lock_path = Path(os.environ.get("TEMP", r"C:\Windows\Temp")) / "trading_watchdog.lock"

    if _lock_path.exists():
        try:
            _old_pid = int(_lock_path.read_text().strip())
            os.kill(_old_pid, 0)          # raises if process is gone
            print(
                f"ERROR: Another watchdog is already running (PID {_old_pid}). "
                "Use start.bat --force to stop it first.",
                flush=True,
            )
            sys.exit(1)
        except (ProcessLookupError, PermissionError):
            pass  # stale lock — process no longer exists
        except (ValueError, OSError):
            pass  # unreadable lock file

    _lock_path.write_text(str(os.getpid()))

    # ── Paths ─────────────────────────────────────────────────────────────────
    SCRIPT_DIR = Path(__file__).parent.resolve()
    LOG_DIR    = SCRIPT_DIR / "logs"
    LOG_DIR.mkdir(exist_ok=True)

    VENV_PYTHON    = str(SCRIPT_DIR / "venv" / "Scripts" / "python.exe")
    VENV_STREAMLIT = str(SCRIPT_DIR / "venv" / "Scripts" / "streamlit.exe")

    # ── Watchdog tunables ─────────────────────────────────────────────────────
    POLL_INTERVAL = 30    # Seconds between liveness checks
    STABLE_UPTIME = 600   # Seconds running without crash → reset back-off counter
    MAX_BACKOFF   = 300   # Cap on restart delay (5 minutes)

    # ── Logging ───────────────────────────────────────────────────────────────
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

    # ── Component definitions ─────────────────────────────────────────────────
    COMPONENTS: dict = {
        "bot": {
            "cmd": [VENV_PYTHON, str(SCRIPT_DIR / "real_bot.py")],
            "startup_delay": 5,
            "log_file": LOG_DIR / "bot_process.log",
        },
        "dashboard": {
            "cmd": [
                VENV_STREAMLIT, "run", str(SCRIPT_DIR / "dashboard.py"),
                "--server.headless",        "true",
                "--server.port",            "8501",
                "--server.fileWatcherType", "none",
            ],
            "startup_delay": 5,
            "log_file": LOG_DIR / "dashboard.log",
        },
    }

    # ── Runtime state ─────────────────────────────────────────────────────────
    processes: dict      = {}
    restart_counts: dict = {}
    start_time: dict     = {}
    _shutting_down       = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def restart_delay(name: str) -> float:
        """Exponential back-off: 30s → 60s → 120s → … → MAX_BACKOFF."""
        count = restart_counts.get(name, 0)
        return min(30 * (2 ** count), MAX_BACKOFF)

    def launch(name: str, wait_after: bool = True) -> subprocess.Popen:
        """Start a component, append its output to its log file, return the Popen."""
        cfg      = COMPONENTS[name]
        log_path = cfg["log_file"]

        logger.info(f"Starting [{name}]: {' '.join(str(c) for c in cfg['cmd'])}")

        log_fh = open(log_path, "a")
        proc   = subprocess.Popen(
            cfg["cmd"],
            stdout=log_fh,
            stderr=log_fh,
            cwd=str(SCRIPT_DIR),
        )
        log_fh.close()  # Safe: child process holds its own fd copy

        processes[name]  = proc
        start_time[name] = time.time()

        if wait_after:
            delay = cfg["startup_delay"]
            logger.info(f"  Waiting {delay}s for [{name}] to initialise…")
            time.sleep(delay)

        return proc

    # ── Shutdown handler ──────────────────────────────────────────────────────

    def shutdown_all(signum=None, frame=None) -> None:
        global _shutting_down
        if _shutting_down:
            return
        _shutting_down = True

        logger.info("Shutdown signal received. Stopping all components…")

        for name in reversed(list(COMPONENTS.keys())):
            proc = processes.get(name)
            if proc and proc.poll() is None:
                logger.info(f"  Terminating [{name}] (PID {proc.pid})…")
                proc.terminate()

        time.sleep(5)

        for name, proc in processes.items():
            if proc and proc.poll() is None:
                logger.info(f"  Force-killing [{name}] (PID {proc.pid})")
                proc.kill()

        try:
            _lock_path.unlink(missing_ok=True)
        except Exception:
            pass

        logger.info("All components stopped. Goodbye.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_all)

    # ── Start-up sequence ─────────────────────────────────────────────────────

    logger.info("=" * 60)
    logger.info("  Trading Bot Watchdog starting (Windows native)")
    logger.info(f"  Script dir   : {SCRIPT_DIR}")
    logger.info(f"  Log dir      : {LOG_DIR}")
    logger.info(f"  Dashboard    : http://localhost:8501")
    logger.info("=" * 60)

    for component_name in ["bot", "dashboard"]:
        try:
            launch(component_name, wait_after=True)
            logger.info(f"  [{component_name}] started (PID {processes[component_name].pid})")
        except Exception as exc:
            logger.error(f"  Failed to start [{component_name}]: {exc}")

    logger.info("All components started. Watchdog monitoring loop active.")
    logger.info(f"Checking every {POLL_INTERVAL}s. Press Ctrl-C to stop everything.\n")

    # ── Monitoring loop ───────────────────────────────────────────────────────

    while not _shutting_down:
        time.sleep(POLL_INTERVAL)

        if _shutting_down:
            break

        for name, proc in list(processes.items()):
            if proc is None:
                continue

            exit_code = proc.poll()
            if exit_code is None:
                uptime = time.time() - start_time.get(name, time.time())
                if uptime >= STABLE_UPTIME and restart_counts.get(name, 0) > 0:
                    logger.info(
                        f"[{name}] stable for {STABLE_UPTIME}s — resetting back-off counter."
                    )
                    restart_counts[name] = 0
                continue

            count = restart_counts.get(name, 0)
            delay = restart_delay(name)

            logger.warning(
                f"[{name}] exited (code={exit_code}). "
                f"Restart #{count + 1} in {delay:.0f}s…"
            )

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
