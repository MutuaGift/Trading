"""
real_bot.py – Autonomous AI trading bot for MT5 (via mt5linux bridge).

Resilience features
───────────────────
• Auto-reconnect  : detects MT5 disconnection and retries MAX_RECONNECT_ATTEMPTS
                    times before exiting (watchdog.py will restart the process).
• Market hours    : sleeps when all configured markets are closed; wakes
                    automatically when the next session opens.
• Weekend guard   : pauses on Fri 22:00 UTC, resumes Sun 22:00 UTC.
• Closed-trade     : tracks open positions by ticket; emits a notification +
  detection         trade-log entry whenever a position is closed (SL/TP hit,
                    manual close, etc.).
• Notifications   : desktop popup (notify-send) + trades.log on every open/close.
"""

from mt5linux import MetaTrader5
mt5 = MetaTrader5(host='localhost', port=18812)
import pandas as pd
import numpy as np
import joblib
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler

from config import (
    SYMBOLS,
    MT5_LOGIN,
    MT5_PASSWORD,
    MT5_SERVER,
    CONFIDENCE_THRESHOLD,
    LOOP_INTERVAL,
    MAGIC,
    DEVIATION,
    LOG_DIR,
    LOG_FILE,
    TRADE_LOG_FILE,
    RESPECT_MARKET_HOURS,
    MARKET_CHECK_INTERVAL,
    MAX_RECONNECT_ATTEMPTS,
    RECONNECT_DELAY,
    NOTIFICATIONS_ENABLED,
)
from notifier import send_notification

# ── Create log directory ──────────────────────────────────────────────────────
os.makedirs(LOG_DIR, exist_ok=True)

# ── Main logger ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=10_000_000, backupCount=5),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ── Trade logger (dedicated file for all trade events) ────────────────────────
trade_logger = logging.getLogger("trades")
trade_logger.setLevel(logging.INFO)
_th = RotatingFileHandler(TRADE_LOG_FILE, maxBytes=5_000_000, backupCount=10)
_th.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
trade_logger.addHandler(_th)
trade_logger.propagate = False  # Don't double-log to root logger

# ── Timeframe map ─────────────────────────────────────────────────────────────
TIMEFRAME_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}

# ── Load ML models ────────────────────────────────────────────────────────────
models = {}
for symbol in SYMBOLS:
    model_file = f"{symbol}_model.pkl"
    if os.path.exists(model_file):
        models[symbol] = joblib.load(model_file)
        logger.info(f"Loaded model for {symbol}: {model_file}")
    else:
        logger.warning(f"No model file for {symbol} ({model_file}). Symbol will be skipped.")

if not models:
    logger.error("No models loaded. Run train_model.py first.")
    sys.exit(1)

# ── Position tracking (for closed-trade detection) ────────────────────────────
# Maps ticket -> mt5 position namedtuple snapshot
_previously_open: dict = {}


# ═════════════════════════════════════════════════════════════════════════════
# Market-hours helpers
# ═════════════════════════════════════════════════════════════════════════════

def is_forex_market_open() -> bool:
    """
    Returns True if the standard forex market is open.
    Open:   Sunday 22:00 UTC  → Friday 22:00 UTC
    Closed: Friday 22:00 UTC  → Sunday 22:00 UTC
    """
    now = datetime.now(timezone.utc)
    wd = now.weekday()   # 0=Mon … 4=Fri, 5=Sat, 6=Sun
    h  = now.hour

    if wd == 5:                   # Saturday — always closed
        return False
    if wd == 6 and h < 22:        # Sunday before 22:00 UTC
        return False
    if wd == 4 and h >= 22:       # Friday after 22:00 UTC
        return False
    return True


def seconds_until_market_open() -> int:
    """Returns seconds until the next Sunday 22:00 UTC market open."""
    now = datetime.now(timezone.utc)
    wd  = now.weekday()  # 0=Mon … 6=Sun

    if wd == 6:
        # Sunday: opens today at 22:00 if not yet passed
        target = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now.hour < 22:
            return max(0, int((target - now).total_seconds()))
        # Already open — shouldn't be calling this
        return 0

    # Otherwise find next Sunday
    days_to_sunday = (6 - wd) % 7 or 7
    target = (now + timedelta(days=days_to_sunday)).replace(
        hour=22, minute=0, second=0, microsecond=0
    )
    return max(0, int((target - now).total_seconds()))


def format_duration(seconds: int) -> str:
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def should_check_symbol(symbol: str, cfg: dict) -> bool:
    """True if this symbol should be processed right now."""
    if cfg.get("market_24_7", False):
        return True          # 24/7 instrument — always check
    if not RESPECT_MARKET_HOURS:
        return True          # Market-hours gating disabled globally
    return is_forex_market_open()


# ═════════════════════════════════════════════════════════════════════════════
# MT5 connection helpers
# ═════════════════════════════════════════════════════════════════════════════

def connect_mt5() -> bool:
    """Initialize MT5 connection with credentials and retry logic."""
    for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
        logger.info(
            f"MT5 initialize attempt {attempt}/{MAX_RECONNECT_ATTEMPTS} "
            f"(login={MT5_LOGIN}, server={MT5_SERVER})…"
        )
        try:
            ok = mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
        except Exception as exc:
            logger.error(
                f"MT5 initialize raised an exception on attempt "
                f"{attempt}/{MAX_RECONNECT_ATTEMPTS}: {exc}. "
                f"Is the mt5linux bridge running?"
            )
            ok = False

        if ok:
            logger.info(
                f"MT5 Initialize SUCCESS — account={MT5_LOGIN}, server={MT5_SERVER}. "
                f"Trading symbols: {list(models.keys())}"
            )
            return True

        error = mt5.last_error()
        logger.warning(
            f"MT5 Initialize FAILED on attempt {attempt}/{MAX_RECONNECT_ATTEMPTS} "
            f"— error code={error[0]}, message='{error[1]}'. "
            f"Retrying in {RECONNECT_DELAY}s…"
        )
        time.sleep(RECONNECT_DELAY)

    logger.error(
        f"MT5 Initialize FAILED after all {MAX_RECONNECT_ATTEMPTS} attempts. "
        f"Last error: {mt5.last_error()}"
    )
    return False


def reconnect_mt5() -> bool:
    """Shut down stale state then reconnect."""
    logger.warning("Reconnecting to MT5…")
    try:
        mt5.shutdown()
    except Exception:
        pass
    return connect_mt5()


def is_mt5_connected() -> bool:
    """Quick liveness check without side effects."""
    try:
        return mt5.terminal_info() is not None
    except Exception:
        return False


# ═════════════════════════════════════════════════════════════════════════════
# Trading logic
# ═════════════════════════════════════════════════════════════════════════════

def has_open_trade(symbol: str) -> bool:
    positions = mt5.positions_get(symbol=symbol)
    return positions is not None and len(positions) > 0


def get_ai_data(symbol: str, timeframe_str: str):
    timeframe = TIMEFRAME_MAP.get(timeframe_str, mt5.TIMEFRAME_M15)
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 100)
    if rates is None:
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")

    df["ma_fast"] = df["close"].rolling(20).mean()
    df["ma_slow"] = df["close"].rolling(50).mean()

    delta = df["close"].diff()
    gain  = delta.where(delta > 0, 0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs    = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    df.dropna(inplace=True)
    return df


def place_trade(symbol: str, order_type: str, lot: float,
                sl_pips: float, tp_pips: float) -> None:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        logger.error(f"[{symbol}] No tick data — market may be closed.")
        return

    if order_type == "BUY":
        price  = tick.ask
        sl     = price - sl_pips
        tp     = price + tp_pips
        mt5_type = mt5.ORDER_TYPE_BUY
    else:
        price  = tick.bid
        sl     = price + sl_pips
        tp     = price - tp_pips
        mt5_type = mt5.ORDER_TYPE_SELL

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       lot,
        "type":         mt5_type,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    DEVIATION,
        "magic":        MAGIC,
        "comment":      "AI Bot",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(
            f"[{symbol}] Order FAILED: {result.comment} (retcode={result.retcode})"
        )
        return

    ticket = result.order
    msg = (
        f"{symbol} | {order_type} | {lot} lot @ {price:.5f} | "
        f"SL={sl:.5f} | TP={tp:.5f} | ticket=#{ticket}"
    )
    logger.info(f"[{symbol}] TRADE OPENED: {msg}")
    trade_logger.info(f"OPENED  | {msg}")

    if NOTIFICATIONS_ENABLED:
        send_notification(
            f"Trade Opened — {symbol}",
            f"{order_type}  {lot} lot @ {price:.5f}\n"
            f"SL: {sl:.5f}   TP: {tp:.5f}\nTicket #{ticket}",
            urgency="normal",
        )


# ═════════════════════════════════════════════════════════════════════════════
# Closed-trade detection
# ═════════════════════════════════════════════════════════════════════════════

def refresh_position_tracker() -> None:
    """
    Compare current open positions against the last snapshot.
    Emit notifications + trade-log entries for any positions that closed.
    """
    global _previously_open

    current: dict = {}
    for symbol in models:
        positions = mt5.positions_get(symbol=symbol)
        if positions:
            for pos in positions:
                current[pos.ticket] = pos

    # Detect closures
    for ticket, pos in _previously_open.items():
        if ticket not in current:
            msg = f"{pos.symbol} | ticket=#{ticket} | was {('BUY' if pos.type == 0 else 'SELL')}"
            logger.info(f"TRADE CLOSED: {msg}")
            trade_logger.info(f"CLOSED  | {msg}")
            if NOTIFICATIONS_ENABLED:
                send_notification(
                    f"Trade Closed — {pos.symbol}",
                    f"Ticket #{ticket} closed\nCheck dashboard for P&L.",
                    urgency="normal",
                )

    _previously_open = current


# ═════════════════════════════════════════════════════════════════════════════
# Main loop
# ═════════════════════════════════════════════════════════════════════════════

if not connect_mt5():
    logger.error(
        "Cannot connect to MT5 after all retries. "
        "Make sure the mt5linux bridge is running."
    )
    sys.exit(1)

logger.info("Bot started. Press Ctrl+C to stop.")

try:
    while True:
        # ── 1. Check whether any symbol should be processed right now ─────────
        active_symbols = {
            sym: cfg
            for sym, cfg in SYMBOLS.items()
            if sym in models and should_check_symbol(sym, cfg)
        }

        if not active_symbols:
            wait = seconds_until_market_open()
            # Cap individual sleep to MARKET_CHECK_INTERVAL so we recheck
            sleep_for = min(wait, MARKET_CHECK_INTERVAL)
            logger.info(
                f"All markets closed (weekend / outside hours). "
                f"Next open in {format_duration(wait)}. "
                f"Sleeping {format_duration(sleep_for)}…"
            )
            time.sleep(sleep_for)
            continue

        # ── 2. Verify MT5 is still alive; reconnect if not ───────────────────
        if not is_mt5_connected():
            if not reconnect_mt5():
                logger.error(
                    "Reconnect failed after all attempts. "
                    "Exiting for watchdog restart."
                )
                sys.exit(1)

        # ── 3. Detect any positions closed since last cycle ───────────────────
        try:
            refresh_position_tracker()
        except Exception as exc:
            logger.warning(f"Position tracker error (non-fatal): {exc}")

        # ── 4. Process each active symbol ────────────────────────────────────
        ts = datetime.now().strftime("%H:%M:%S")

        for symbol, cfg in active_symbols.items():
            try:
                model     = models[symbol]
                lot       = cfg["lot"]
                sl_pips   = cfg["sl_pips"]
                tp_pips   = cfg["tp_pips"]
                timeframe = cfg["timeframe"]

                if has_open_trade(symbol):
                    logger.info(f"[{symbol}] [{ts}] Trade already open. Skipping.")
                    continue

                df = get_ai_data(symbol, timeframe)
                if df is None or df.empty:
                    logger.info(f"[{symbol}] [{ts}] No market data. Waiting…")
                    continue

                last     = df.iloc[-1]
                features = np.array(
                    [last["rsi"], last["ma_fast"], last["ma_slow"]]
                ).reshape(1, -1)

                proba      = model.predict_proba(features)[0]
                confidence = max(proba)
                prediction = model.predict(features)[0]

                if confidence < CONFIDENCE_THRESHOLD:
                    logger.info(
                        f"[{symbol}] [{ts}] Signal too weak "
                        f"(confidence={confidence:.2f}). Skipping."
                    )
                elif prediction == 1:
                    logger.info(
                        f"[{symbol}] [{ts}] AI SIGNAL: BUY "
                        f"(confidence={confidence:.2f}). Executing…"
                    )
                    place_trade(symbol, "BUY", lot, sl_pips, tp_pips)
                else:
                    logger.info(
                        f"[{symbol}] [{ts}] AI SIGNAL: SELL "
                        f"(confidence={confidence:.2f}). Executing…"
                    )
                    place_trade(symbol, "SELL", lot, sl_pips, tp_pips)

            except Exception as exc:
                logger.error(f"[{symbol}] Unexpected error: {exc}")
                # If it looks like an MT5 connection issue, trigger reconnect
                if not is_mt5_connected():
                    logger.warning("MT5 appears disconnected. Reconnecting…")
                    if not reconnect_mt5():
                        logger.error("Reconnect failed. Exiting for watchdog restart.")
                        sys.exit(1)
                    break  # Restart the inner symbol loop after reconnect

        time.sleep(LOOP_INTERVAL)

except KeyboardInterrupt:
    logger.info("Shutdown requested. Closing MT5 connection…")
    mt5.shutdown()
    logger.info("Bot stopped cleanly.")
except Exception as exc:
    logger.exception(f"Fatal unhandled error: {exc}")
    try:
        mt5.shutdown()
    except Exception:
        pass
    sys.exit(1)
