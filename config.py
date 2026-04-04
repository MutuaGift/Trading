# All trading settings live here. Edit this file to change bot behavior.

SYMBOLS = {
    "BTCUSD": {
        "lot":          0.01,
        "sl_pips":      500.0,     # 500 pips (BTC is extremely volatile)
        "tp_pips":      1000.0,    # 1000 pips
        "timeframe":    "M15",
        "market_24_7":  True,      # BTC trades around the clock — ignore forex hours
    },
    "EURUSD": {
        "lot":          0.10,
        "sl_pips":      50.0,
        "tp_pips":      100.0,
        "timeframe":    "M15",
        "market_24_7":  False,   # Respect standard forex hours
    },
    "XAUUSD": {
        "lot":          0.01,
        "sl_pips":      100.0,
        "tp_pips":      200.0,
        "timeframe":    "M15",
        "market_24_7":  False,
    },
    "USDJPY": {
        "lot":          0.01,
        "sl_pips":      50.0,
        "tp_pips":      100.0,
        "timeframe":    "M15",
        "market_24_7":  False,
    },
    "GBPUSD": {
        "lot":          0.01,
        "sl_pips":      50.0,
        "tp_pips":      100.0,
        "timeframe":    "M15",
        "market_24_7":  False,
    },
    "USOIL": {
        "lot":          0.01,
        "sl_pips":      50.0,
        "tp_pips":      100.0,
        "timeframe":    "M15",
        "market_24_7":  False,
    },
    "UKOIL": {
        "lot":          0.01,
        "sl_pips":      50.0,
        "tp_pips":      100.0,
        "timeframe":    "M15",
        "market_24_7":  False,
    },
}

# ── MT5 Account credentials ───────────────────────────────────────────────────
MT5_LOGIN    = 57423210
MT5_PASSWORD = "Gif4lovesmusic#"
MT5_SERVER   = "HFMarketsKE-Demo2"

CONFIDENCE_THRESHOLD = 0.60   # Minimum model confidence to place a trade
LOOP_INTERVAL        = 60     # Seconds between each market check
MAGIC                = 123    # MT5 magic number to identify our bot's trades
DEVIATION            = 10     # Max price deviation allowed on order execution

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_DIR        = "logs"
LOG_FILE       = "logs/bot.log"        # General bot activity
TRADE_LOG_FILE = "logs/trades.log"     # Trade-specific events (opened / closed)

# ── Market hours (UTC) ────────────────────────────────────────────────────────
# Forex opens Sunday 22:00 UTC and closes Friday 22:00 UTC.
# Symbols with market_24_7=True are always processed regardless of this setting.
RESPECT_MARKET_HOURS  = True    # Set False to bypass market-hours gating globally
MARKET_CHECK_INTERVAL = 300     # Seconds to sleep when all markets are closed (5 min)

# ── Auto-reconnect ────────────────────────────────────────────────────────────
MAX_RECONNECT_ATTEMPTS = 10
RECONNECT_DELAY        = 30    # Seconds between reconnect attempts

# ── Desktop notifications (notify-send / libnotify) ──────────────────────────
NOTIFICATIONS_ENABLED = True
