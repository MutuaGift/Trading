"""
enable_algo_trading.py — Ensures MetaTrader 5 AutoTrading is enabled.

Checks the Algo Trading toolbar button state and clicks it if OFF.
Uses Python Xlib to interact with the MT5 GUI on the Xvfb display.
Called by the watchdog after MT5 fully loads.
"""

import sys
import time
import os
import logging

DISPLAY = os.environ.get("VIRT_DISPLAY", os.environ.get("DISPLAY", ":99"))

logger = logging.getLogger("enable_algo_trading")

# Algo Trading button position in the MT5 toolbar (for 1024x768 Xvfb)
ALGO_BTN_X = 293
ALGO_BTN_Y = 63

# Colour thresholds to detect ON (green) vs OFF (red)
# OFF = red icon, ON = green icon at the button position
# We sample a pixel slightly to the LEFT of the text (the icon area)
ICON_X = 287
ICON_Y = 63


def _get_pixel_rgb(display, x, y):
    """Return (r, g, b) of a single screen pixel."""
    screen = display.screen()
    root = screen.root
    # Use XGetImage to read pixels
    img = root.get_image(x, y, 1, 1, 0x00FFFFFF, 2)  # ZPixmap
    data = img.data
    if isinstance(data, bytes):
        b = data[0] if len(data) > 0 else 0
        g = data[1] if len(data) > 1 else 0
        r = data[2] if len(data) > 2 else 0
        return (r, g, b)
    return (0, 0, 0)


def _click(display, x, y):
    """Single left-click at (x, y) on the display."""
    import Xlib.ext.xtest
    import Xlib.X
    Xlib.ext.xtest.fake_input(display, Xlib.X.MotionNotify, x=x, y=y)
    display.sync()
    time.sleep(0.05)
    Xlib.ext.xtest.fake_input(display, Xlib.X.ButtonPress, 1, x=x, y=y)
    display.sync()
    time.sleep(0.05)
    Xlib.ext.xtest.fake_input(display, Xlib.X.ButtonRelease, 1, x=x, y=y)
    display.sync()
    time.sleep(0.3)


def is_algo_trading_on(display):
    """
    Return True if AutoTrading button appears to be ON (green icon).
    Checks the pixel at the icon position.
    """
    r, g, b = _get_pixel_rgb(display, ICON_X, ICON_Y)
    logger.debug(f"Algo Trading button pixel at ({ICON_X},{ICON_Y}): R={r} G={g} B={b}")
    # Green = ON: G > 100 and G > R
    # Red = OFF: R > 100 and R > G
    if g > 100 and g > r:
        return True
    if r > 100 and r > g:
        return False
    # Ambiguous — assume OFF to be safe
    return False


def enable_algo_trading(max_wait=300, check_interval=10):
    """
    Wait for MT5 to fully load, then ensure AutoTrading is ON.
    Returns True if AutoTrading was confirmed ON, False if timed out.
    """
    try:
        import Xlib.display
    except ImportError:
        logger.warning("python-xlib not available — skipping AutoTrading check.")
        return False

    logger.info(f"Connecting to display {DISPLAY} to check AutoTrading state...")
    try:
        display = Xlib.display.Display(DISPLAY)
    except Exception as e:
        logger.warning(f"Cannot connect to {DISPLAY}: {e}")
        return False

    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        try:
            if is_algo_trading_on(display):
                logger.info("AutoTrading is already ON — nothing to do.")
                display.close()
                return True

            logger.info("AutoTrading is OFF — clicking the Algo Trading button...")
            _click(display, ALGO_BTN_X, ALGO_BTN_Y)
            time.sleep(2)

            if is_algo_trading_on(display):
                logger.info("AutoTrading is now ON.")
                display.close()
                return True

            logger.warning("Button click didn't enable AutoTrading — retrying...")
        except Exception as e:
            logger.debug(f"Pixel check error: {e}")

        time.sleep(check_interval)

    logger.error("Timed out waiting for AutoTrading to be enabled.")
    display.close()
    return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [ALGO] %(message)s")
    success = enable_algo_trading(max_wait=int(sys.argv[1]) if len(sys.argv) > 1 else 300)
    sys.exit(0 if success else 1)
