import MetaTrader5 as mt5
import pandas as pd
import numpy as np

from config import SYMBOLS

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

NUM_CANDLES    = 10000
FUTURE_LOOKAHEAD = 5


def build_dataset(symbol, timeframe_str):
    csv_file  = f"{symbol}_data.csv"
    timeframe = TIMEFRAME_MAP.get(timeframe_str, mt5.TIMEFRAME_M15)

    print(f"\nDownloading {NUM_CANDLES} candles for {symbol} ({timeframe_str})...")
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, NUM_CANDLES)

    if rates is None:
        print(f"ERROR: Could not get data for {symbol}. Make sure it is in Market Watch.")
        return

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')

    print(f"Calculating indicators for {symbol}...")
    df['MA_FAST'] = df['close'].rolling(20).mean()
    df['MA_SLOW'] = df['close'].rolling(50).mean()

    delta = df['close'].diff()
    gain  = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs    = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    df['future_close'] = df['close'].shift(-FUTURE_LOOKAHEAD)
    df['RESULT'] = np.where(df['future_close'] > df['close'], 1, 0)

    df.dropna(inplace=True)

    final = df[['RSI', 'MA_FAST', 'MA_SLOW', 'RESULT']]
    final.to_csv(csv_file, index=False)
    print(f"Saved {len(final)} rows to {csv_file}")


if __name__ == "__main__":
    print("Connecting to MT5...")
    if not mt5.initialize():
        print("ERROR: MT5 initialization failed. Is the terminal open?")
        exit()

    for symbol, cfg in SYMBOLS.items():
        build_dataset(symbol, cfg["timeframe"])

    mt5.shutdown()
    print("\nAll datasets built.")
