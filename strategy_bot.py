from mt5linux import MetaTrader5 as mt5
import pandas as pd

mt5.initialize()

symbol = "EURUSD"
lot = 0.01

# SL = 20 pips, TP = 40 pips (5-digit broker: 1 pip = 0.0001 * 10 points = 0.00010)
SL_PIPS = 0.0020
TP_PIPS = 0.0040

# -------- OPEN POSITION GUARD --------
positions = mt5.positions_get(symbol=symbol)
if positions is not None and len(positions) > 0:
    print(f"Position already open for {symbol}. Skipping new trade.")
    mt5.shutdown()
    exit()

# -------- GET MARKET DATA --------
rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 100)
if rates is None:
    print("ERROR: Could not retrieve market data.")
    mt5.shutdown()
    exit()

df = pd.DataFrame(rates)

# calculate moving averages
df['ma10'] = df['close'].rolling(10).mean()
df['ma20'] = df['close'].rolling(20).mean()

# get latest values
last = df.iloc[-1]

# get price
tick = mt5.symbol_info_tick(symbol)
if tick is None:
    print("ERROR: Could not get tick data. Market may be closed.")
    mt5.shutdown()
    exit()

# BUY condition
if last['ma10'] > last['ma20']:
    print("BUY SIGNAL")
    price = tick.ask
    sl = price - SL_PIPS
    tp = price + TP_PIPS

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": mt5.ORDER_TYPE_BUY,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 10,
        "magic": 100,
        "comment": "MA Buy",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Order FAILED: {result.comment} (retcode={result.retcode})")
    else:
        print(f"BUY order placed at {price} | SL={sl} | TP={tp}")

# SELL condition
elif last['ma10'] < last['ma20']:
    print("SELL SIGNAL")
    price = tick.bid
    sl = price + SL_PIPS
    tp = price - TP_PIPS

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 10,
        "magic": 100,
        "comment": "MA Sell",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Order FAILED: {result.comment} (retcode={result.retcode})")
    else:
        print(f"SELL order placed at {price} | SL={sl} | TP={tp}")

# FLAT condition — MAs are equal, stay out
else:
    print("MA10 == MA20: No signal. Staying flat.")

mt5.shutdown()
