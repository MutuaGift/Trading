from mt5linux import MetaTrader5 as mt5
import pandas as pd

from config import SYMBOLS, MAGIC, DEVIATION

# -------- TIMEFRAME MAP --------
TIMEFRAME_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}

mt5.initialize()

for symbol, cfg in SYMBOLS.items():
    lot       = cfg["lot"]
    sl_pips   = cfg["sl_pips"]
    tp_pips   = cfg["tp_pips"]
    timeframe = TIMEFRAME_MAP.get(cfg["timeframe"], mt5.TIMEFRAME_M15)

    print(f"\n--- Checking {symbol} ---")

    # -------- OPEN POSITION GUARD --------
    positions = mt5.positions_get(symbol=symbol)
    if positions is not None and len(positions) > 0:
        print(f"[{symbol}] Position already open. Skipping.")
        continue

    # -------- GET MARKET DATA --------
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 100)
    if rates is None:
        print(f"[{symbol}] ERROR: Could not retrieve market data.")
        continue

    df = pd.DataFrame(rates)
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df.dropna(inplace=True)

    if df.empty:
        print(f"[{symbol}] Not enough data to compute MAs.")
        continue

    last = df.iloc[-1]

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"[{symbol}] ERROR: Could not get tick data. Market may be closed.")
        continue

    # -------- SIGNAL LOGIC --------
    if last['ma10'] > last['ma20']:
        print(f"[{symbol}] BUY SIGNAL")
        price = tick.ask
        sl = price - sl_pips
        tp = price + tp_pips
        order_type = mt5.ORDER_TYPE_BUY
        comment = "MA Buy"

    elif last['ma10'] < last['ma20']:
        print(f"[{symbol}] SELL SIGNAL")
        price = tick.bid
        sl = price + sl_pips
        tp = price - tp_pips
        order_type = mt5.ORDER_TYPE_SELL
        comment = "MA Sell"

    else:
        print(f"[{symbol}] MA10 == MA20: No signal. Staying flat.")
        continue

    # -------- PLACE ORDER --------
    request = {
        "action":      mt5.TRADE_ACTION_DEAL,
        "symbol":      symbol,
        "volume":      lot,
        "type":        order_type,
        "price":       price,
        "sl":          sl,
        "tp":          tp,
        "deviation":   DEVIATION,
        "magic":       MAGIC,
        "comment":     comment,
        "type_time":   mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"[{symbol}] Order FAILED: {result.comment} (retcode={result.retcode})")
    else:
        print(f"[{symbol}] Order placed at {price} | SL={sl} | TP={tp}")

mt5.shutdown()
