"""
notifier.py – Desktop + log notifications for trade events.

Uses notify-send (libnotify) when available; always writes to the log.
Install libnotify on Arch Linux: sudo pacman -S libnotify
"""

import subprocess
import os
import logging

logger = logging.getLogger(__name__)


def send_notification(title: str, message: str, urgency: str = "normal") -> None:
    """
    Send a desktop notification and log the event.

    urgency: "low" | "normal" | "critical"
    """
    logger.info(f"NOTIFY | {title} | {message}")

    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    # Required for notify-send to reach the session bus when called from a
    # background process.  Best-effort: if it fails, we fall back to log-only.
    if "DBUS_SESSION_BUS_ADDRESS" not in env:
        # Try to read it from /run/user/<uid>/bus (systemd default)
        uid = os.getuid()
        env.setdefault(
            "DBUS_SESSION_BUS_ADDRESS",
            f"unix:path=/run/user/{uid}/bus",
        )

    try:
        subprocess.run(
            [
                "notify-send",
                "--urgency", urgency,
                "--app-name", "TradingBot",
                "--icon", "dialog-information",
                title,
                message,
            ],
            env=env,
            timeout=5,
            capture_output=True,
        )
    except FileNotFoundError:
        # notify-send not installed — silent fallback to log-only
        pass
    except Exception as exc:
        logger.debug(f"Desktop notification failed (non-fatal): {exc}")
