"""
notifier.py – Desktop notifications for trade events on Windows.

Uses plyer for cross-platform desktop notifications (Windows toast).
Falls back to log-only if plyer is unavailable.

Install: pip install plyer
"""

import logging

logger = logging.getLogger(__name__)


def send_notification(title: str, message: str, urgency: str = "normal") -> None:
    """
    Send a Windows desktop notification and log the event.

    urgency: "low" | "normal" | "critical"  (used for log level only on Windows)
    """
    logger.info(f"NOTIFY | {title} | {message}")

    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="TradingBot",
            timeout=8,
        )
    except ImportError:
        # plyer not installed — log-only fallback
        pass
    except Exception as exc:
        logger.debug(f"Desktop notification failed (non-fatal): {exc}")
