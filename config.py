# All trading settings live here. Edit this file to change bot behavior.

SYMBOLS = {
    "EURUSD": {
        "lot":       0.01,
        "sl_pips":   0.0020,   # 20 pips
        "tp_pips":   0.0040,   # 40 pips
        "timeframe": "M15",
    },
    "XAUUSD": {
        "lot":       0.01,
        "sl_pips":   1.50,     # 150 pips (Gold moves in dollars not micro pips)
        "tp_pips":   3.00,     # 300 pips
        "timeframe": "M15",
    },
    "BTCUSD": {
        "lot":       0.01,
        "sl_pips":   500.0,    # 500 pips (BTC is extremely volatile)
        "tp_pips":   1000.0,   # 1000 pips
        "timeframe": "M15",
    },
}

CONFIDENCE_THRESHOLD = 0.60   # Minimum model confidence to place a trade
LOOP_INTERVAL        = 60     # Seconds between each market check
MAGIC                = 123    # MT5 magic number to identify our bot's trades
DEVIATION            = 10     # Max price deviation allowed on order execution
LOG_FILE             = "bot.log"
