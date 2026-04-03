from mt5linux import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from config import SYMBOL  # Assuming you still have your config file with EURUSD!

# -------- SETTINGS --------
TIMEFRAME = mt5.TIMEFRAME_M5
NUM_CANDLES = 10000
FUTURE_LOOKAHEAD = 5  # How many candles into the future we look to judge a "good" trade

def build_dataset():
    print(f"📥 Connecting to MT5 to harvest data for {SYMBOL}...")
    
    if not mt5.initialize():
        print("🚨 ERROR: MT5 initialization failed. Is the terminal open?")
        return

    # 1. Download the raw candles
    print(f"⏳ Downloading {NUM_CANDLES} candles. This might take a few seconds...")
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, NUM_CANDLES)
    
    if rates is None:
        print(f"🚨 ERROR: Could not get data. Make sure {SYMBOL} is in your Market Watch.")
        mt5.shutdown()
        return

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    print("🧮 Calculating Indicators (RSI, MA Fast, MA Slow)...")
    
    # 2. Calculate Features (MAs)
    df['MA_FAST'] = df['close'].rolling(20).mean()
    df['MA_SLOW'] = df['close'].rolling(50).mean()
    
    # Calculate Features (RSI)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # 3. Create the "Time Machine" Target Variable (RESULT)
    print(f"🔮 Analyzing the future ({FUTURE_LOOKAHEAD} candles ahead) to label the data...")
    # .shift(-5) pulls the closing price from 5 rows down into the current row
    df['future_close'] = df['close'].shift(-FUTURE_LOOKAHEAD)
    
    # If the future price is greater than the current close, it's a 1 (BUY). Otherwise, 0 (SELL).
    df['RESULT'] = np.where(df['future_close'] > df['close'], 1, 0)

    # 4. Clean up the data
    # Drop rows with NaN (the first 50 rows won't have a Slow MA, and the last 5 rows won't have a future_close)
    df.dropna(inplace=True)

    # 5. Extract only what the AI needs and save it
    final_dataset = df[['RSI', 'MA_FAST', 'MA_SLOW', 'RESULT']]
    
    print("💾 Saving to market_data.csv...")
    final_dataset.to_csv("market_data.csv", index=False)
    
    print(f"✅ SUCCESS: Dataset created with {len(final_dataset)} rows!")
    mt5.shutdown()

if __name__ == "__main__":
    build_dataset()
