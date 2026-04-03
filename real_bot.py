from mt5linux import MetaTrader5 as mt5
import pandas as pd
import time
import joblib
import numpy as np
import logging
import os
from datetime import datetime

from config import SYMBOLS, CONFIDENCE_THRESHOLD, LOOP_INTERVAL, MAGIC, DEVIATION, LOG_FILE

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

# -------- LOGGING SETUP --------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# -------- LOAD MODELS --------
models = {}
for symbol in SYMBOLS:
    model_file = f"{symbol}_model.pkl"
    if os.path.exists(model_file):
        models[symbol] = joblib.load(model_file)
        logger.info(f"Loaded model for {symbol}: {model_file}")
    else:
        logger.warning(f"No model file found for {symbol} ({model_file}). Symbol will be skipped.")

if not models:
    logger.error("No models loaded. Run train_model.py first.")
    exit()

# -------- INIT MT5 --------
if not mt5.initialize():
    logger.error("MT5 connection failed")
    exit()
logger.info(f"Connected to MT5. Trading symbols: {list(models.keys())}")

# -------- FUNCTIONS --------
def has_open_trade(symbol):
    positions = mt5.positions_get(symbol=symbol)
    return positions is not None and len(positions) > 0

def get_ai_data(symbol, timeframe_str):
    timeframe = TIMEFRAME_MAP.get(timeframe_str, mt5.TIMEFRAME_M15)
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 100)
    if rates is None:
        return None

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')

    df['ma_fast'] = df['close'].rolling(20).mean()
    df['ma_slow'] = df['close'].rolling(50).mean()

    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    df.dropna(inplace=True)
    return df

def place_trade(symbol, order_type, lot, sl_pips, tp_pips):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        logger.error(f"[{symbol}] Market closed or tick data unavailable.")
        return

    if order_type == "BUY":
        price = tick.ask
        sl = price - sl_pips
        tp = price + tp_pips
        order = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid
        sl = price + sl_pips
        tp = price - tp_pips
        order = mt5.ORDER_TYPE_SELL

    request = {
        "action":      mt5.TRADE_ACTION_DEAL,
        "symbol":      symbol,
        "volume":      lot,
        "type":        order,
        "price":       price,
        "sl":          sl,
        "tp":          tp,
        "deviation":   DEVIATION,
        "magic":       MAGIC,
        "comment":     "AI Bot Trade",
        "type_time":   mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"[{symbol}] Order Failed: {result.comment} (retcode={result.retcode})")
    else:
        logger.info(f"[{symbol}] TRADE PLACED: {order_type} at {price} | SL={sl} | TP={tp}")

# -------- MAIN LOOP --------
try:
    while True:
        current_time = datetime.now().strftime("%H:%M:%S")

        for symbol, cfg in SYMBOLS.items():
            if symbol not in models:
                continue

            model = models[symbol]
            lot       = cfg["lot"]
            sl_pips   = cfg["sl_pips"]
            tp_pips   = cfg["tp_pips"]
            timeframe = cfg["timeframe"]

            if has_open_trade(symbol):
                logger.info(f"[{symbol}] [{current_time}] Trade already open. Skipping.")
                continue

            df = get_ai_data(symbol, timeframe)
            if df is None or df.empty:
                logger.info(f"[{symbol}] [{current_time}] Waiting for market data...")
                continue

            last = df.iloc[-1]
            features = np.array([last['rsi'], last['ma_fast'], last['ma_slow']]).reshape(1, -1)

            proba      = model.predict_proba(features)[0]
            confidence = max(proba)
            prediction = model.predict(features)[0]

            if confidence < CONFIDENCE_THRESHOLD:
                logger.info(f"[{symbol}] [{current_time}] Signal too weak (confidence={confidence:.2f}). Skipping.")
            elif prediction == 1:
                logger.info(f"[{symbol}] [{current_time}] AI SIGNAL: BUY (confidence={confidence:.2f}). Executing trade...")
                place_trade(symbol, "BUY", lot, sl_pips, tp_pips)
            else:
                logger.info(f"[{symbol}] [{current_time}] AI SIGNAL: SELL (confidence={confidence:.2f}). Executing trade...")
                place_trade(symbol, "SELL", lot, sl_pips, tp_pips)

        time.sleep(LOOP_INTERVAL)

except KeyboardInterrupt:
    logger.info("Shutdown requested. Closing MT5 connection...")
    mt5.shutdown()
    logger.info("Bot stopped cleanly.")
except Exception as e:
    logger.exception(f"Unexpected error: {e}")
    mt5.shutdown()
