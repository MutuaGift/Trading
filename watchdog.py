"""
watchdog.py – Starts and monitors every component of the trading stack.

Components managed
──────────────────
  1. MetaTrader 5   (Wine on DISPLAY=:0, minimized, runs mt5_bridge_ea.mq5)
  2. real_bot.py    (AI trading loop, uses mt5_file_bridge.py)
  3. dashboard.py   (Streamlit UI)

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

# ── Imports only at module level — no executable code so that importing this
# module (e.g. by streamlit's file-watcher) has zero side-effects.
import os
import sys
import fcntl
import signal
import subprocess
import time
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler


if __name__ == "__main__":

    # ── Single-instance guard ─────────────────────────────────────────────────
    # Prevents a second watchdog from starting whether via start.sh or directly.
    # Uses a non-blocking exclusive flock so the check is instant.
    _lock_fh = open("/tmp/trading_watchdog.lock", "w")
    try:
        fcntl.flock(_lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        print("ERROR: Another watchdog instance is already running. Exiting.", flush=True)
        sys.exit(1)

    # ── Paths ─────────────────────────────────────────────────────────────────
    SCRIPT_DIR = Path(__file__).parent.resolve()
    LOG_DIR    = SCRIPT_DIR / "logs"
    LOG_DIR.mkdir(exist_ok=True)

    VENV_PYTHON    = str(SCRIPT_DIR / "venv" / "bin" / "python")
    VENV_STREAMLIT = str(SCRIPT_DIR / "venv" / "bin" / "streamlit")

    # ── Watchdog tunables ─────────────────────────────────────────────────────
    POLL_INTERVAL  = 30    # Seconds between liveness checks
    STABLE_UPTIME  = 600   # Seconds running without crash → reset back-off counter
    MAX_BACKOFF    = 300   # Cap on restart delay (5 minutes)

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
    # Use the real X display so MT5/Wine render on screen.
    DISPLAY = ":0"

    # MT5 login config — Z: drive is Wine's view of the Linux filesystem root
    _mt5_config_linux = SCRIPT_DIR / "mt5_login.ini"
    _mt5_config_wine  = "Z:" + str(_mt5_config_linux).replace("/", "\\")

    COMPONENTS: dict = {
        # ── MetaTrader 5 terminal ─────────────────────────────────────────────
        # Runs on DISPLAY=:0 (real X display) so Wine can auto-login without Xvfb.
        # The mt5_bridge_ea.mq5 Expert Advisor provides file-based IPC.
        # The /config flag logs in automatically (Wine Z: = Linux /).
        "mt5": {
            "cmd": [
                "wine",
                "C:/Program Files/MetaTrader 5/terminal64.exe",
                f"/config:{_mt5_config_wine}",
                "/minimized",
            ],
            "startup_delay": 45,   # MT5 needs time to start, log in, and load EA
            "use_display":   True,
            "log_file":      LOG_DIR / "mt5.log",
        },
        "bot": {
            "cmd": [VENV_PYTHON, str(SCRIPT_DIR / "real_bot.py")],
            "startup_delay": 5,
            "use_display":   False,
            "log_file":      LOG_DIR / "bot_process.log",
        },
        "dashboard": {
            "cmd": [
                VENV_STREAMLIT, "run", str(SCRIPT_DIR / "dashboard.py"),
                "--server.headless",      "true",
                "--server.port",          "8501",
                "--server.fileWatcherType", "none",  # Don't scan .py files
            ],
            "startup_delay": 5,
            "use_display":   False,
            "log_file":      LOG_DIR / "dashboard.log",
        },
    }

    # ── Runtime state ─────────────────────────────────────────────────────────
    processes: dict      = {}
    restart_counts: dict = {}
    last_crash_time: dict = {}
    start_time: dict     = {}
    _shutting_down       = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def build_env(use_display: bool, extra_env: dict = None) -> dict:
        env = os.environ.copy()
        if use_display:
            env["DISPLAY"] = DISPLAY
        if extra_env:
            env.update(extra_env)
        return env

    def restart_delay(name: str) -> float:
        """Exponential back-off: 30s → 60s → 120s → … → MAX_BACKOFF."""
        count = restart_counts.get(name, 0)
        return min(30 * (2 ** count), MAX_BACKOFF)

    def launch(name: str, wait_after: bool = True) -> subprocess.Popen:
        """Start a component, append its output to its log file, return the Popen."""
        cfg      = COMPONENTS[name]
        log_path = cfg["log_file"]
        env      = build_env(cfg["use_display"], cfg.get("extra_env"))

        logger.info(f"Starting [{name}]: {' '.join(str(c) for c in cfg['cmd'])}")

        log_fh = open(log_path, "a")
        proc   = subprocess.Popen(
            cfg["cmd"],
            stdout=log_fh,
            stderr=log_fh,
            env=env,
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

        logger.info("All components stopped. Goodbye.")
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown_all)
    signal.signal(signal.SIGTERM, shutdown_all)

    # ── Start-up sequence ─────────────────────────────────────────────────────

    logger.info("=" * 60)
    logger.info("  Trading Bot Watchdog starting")
    logger.info(f"  Script dir   : {SCRIPT_DIR}")
    logger.info(f"  Log dir      : {LOG_DIR}")
    logger.info(f"  Display      : {DISPLAY}  (real X display, MT5 minimized)")
    logger.info(f"  Dashboard    : http://localhost:8501")
    logger.info(f"  MT5 config   : {_mt5_config_linux}")
    logger.info("=" * 60)

    # Kill any stale Wine / dashboard processes before starting fresh.
    # Killing wineserver ensures MT5 starts in a clean state.
    # Streamlit drifts to port 8502/8503 if 8501 is still bound.
    logger.info("Clearing any stale MT5 / dashboard / wine processes before startup…")
    subprocess.run(["pkill", "-KILL", "-f", "terminal64.exe"], capture_output=True)
    subprocess.run(["pkill", "-KILL", "-f", "streamlit"],       capture_output=True)
    subprocess.run(["pkill", "-KILL", "-f", "wine"],            capture_output=True)
    subprocess.run(["pkill", "-KILL",        "wineserver"],     capture_output=True)
    time.sleep(5)  # Give wineserver time to fully release IPC handles

    for component_name in ["mt5", "bot", "dashboard"]:
        try:
            launch(component_name, wait_after=True)
            logger.info(f"  [{component_name}] started (PID {processes[component_name].pid})")
        except Exception as exc:
            logger.error(f"  Failed to start [{component_name}]: {exc}")

    # ── Enable AutoTrading in MT5 (runs in background while bot retries) ─────
    # MT5 sometimes starts with Algo Trading disabled; this clicks the button.
    logger.info("Launching AutoTrading enabler in background (max 8 min wait)…")
    subprocess.Popen(
        [VENV_PYTHON, str(SCRIPT_DIR / "enable_algo_trading.py"), "480"],
        env={**os.environ, "DISPLAY": DISPLAY},
    )

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
            last_crash_time[name] = time.time()

            time.sleep(delay)

            if _shutting_down:
                break

            restart_counts[name] = count + 1

            # ── Pre-restart cleanup ───────────────────────────────────────────
            if name == "mt5":
                # Kill any stale Wine/wineserver state before restarting MT5.
                logger.info("Killing wineserver before MT5 restart…")
                subprocess.run(["pkill", "-KILL", "-f", "terminal64.exe"], capture_output=True)
                subprocess.run(["pkill", "-KILL", "-f", "wine"],            capture_output=True)
                subprocess.run(["pkill", "-KILL",        "wineserver"],     capture_output=True)
                time.sleep(5)

            try:
                launch(name, wait_after=False)
                logger.info(
                    f"[{name}] restarted (PID {processes[name].pid}, "
                    f"attempt #{restart_counts[name]})"
                )
                # Re-enable AutoTrading after MT5 restart
                if name == "mt5":
                    subprocess.Popen(
                        [VENV_PYTHON, str(SCRIPT_DIR / "enable_algo_trading.py"), "480"],
                        env={**os.environ, "DISPLAY": DISPLAY},
                    )
            except Exception as exc:
                logger.error(f"Failed to restart [{name}]: {exc}")
