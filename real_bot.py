from mt5linux import MetaTrader5 as mt5
import pandas as pd
import time
import joblib
import numpy as np
import logging
from datetime import datetime

# -------- LOGGING SETUP --------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# -------- SETTINGS --------
SYMBOL = "EURUSD"
LOT_SIZE = 0.01
CONFIDENCE_THRESHOLD = 0.60

# -------- LOAD AI MODEL --------
logger.info("Loading AI Model...")
try:
    model = joblib.load("model.pkl")
    logger.info("Model loaded successfully!")
except FileNotFoundError:
    logger.error("model.pkl not found!")
    exit()

# -------- INIT --------
if not mt5.initialize():
    logger.error("MT5 connection failed")
    exit()
logger.info(f"Connected to MT5. Starting automated trading for {SYMBOL}...")

# -------- FUNCTIONS --------
def has_open_trade():
    positions = mt5.positions_get(symbol=SYMBOL)
    return positions is not None and len(positions) > 0

def get_ai_data():
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 100)
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

def place_trade(order_type):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        logger.error("Market closed or tick data unavailable.")
        return

    if order_type == "BUY":
        price = tick.ask
        sl = price - 0.0020
        tp = price + 0.0040
        order = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid
        sl = price + 0.0020
        tp = price - 0.0040
        order = mt5.ORDER_TYPE_SELL

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": LOT_SIZE,
        "type": order,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 10,
        "magic": 123,
        "comment": "AI Bot Trade",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Order Failed: {result.comment} (retcode={result.retcode})")
    else:
        logger.info(f"TRADE PLACED: {order_type} at {price}")

# -------- MAIN LOOP --------
try:
    while True:
        current_time = datetime.now().strftime("%H:%M:%S")

        if not has_open_trade():
            df = get_ai_data()

            if df is not None and not df.empty:
                last = df.iloc[-1]
                features = np.array([last['rsi'], last['ma_fast'], last['ma_slow']]).reshape(1, -1)

                proba = model.predict_proba(features)[0]
                confidence = max(proba)
                prediction = model.predict(features)[0]

                if confidence < CONFIDENCE_THRESHOLD:
                    logger.info(f"[{current_time}] Signal too weak (confidence={confidence:.2f}). Skipping.")
                elif prediction == 1:
                    logger.info(f"[{current_time}] AI SIGNAL: BUY (confidence={confidence:.2f}). Executing trade...")
                    place_trade("BUY")
                else:
                    logger.info(f"[{current_time}] AI SIGNAL: SELL (confidence={confidence:.2f}). Executing trade...")
                    place_trade("SELL")
            else:
                logger.info(f"[{current_time}] Waiting for market data...")
        else:
            logger.info(f"[{current_time}] Trade already open. Managing risk...")

        time.sleep(60)

except KeyboardInterrupt:
    logger.info("Shutdown requested. Closing MT5 connection...")
    mt5.shutdown()
    logger.info("Bot stopped cleanly.")
except Exception as e:
    logger.exception(f"Unexpected error: {e}")
    mt5.shutdown()
