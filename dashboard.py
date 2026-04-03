import streamlit as st
from mt5linux import MetaTrader5 as mt5
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import ccxt 
import joblib
import numpy as np

# -------- PAGE CONFIG & STYLING --------
st.set_page_config(page_title="AI Trading Dashboard", layout="wide")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stApp { background-color: #0E1117; }
    div[data-testid="stMetricValue"] {
        font-size: 2.2rem;
        color: #00FFAA;
        font-family: 'Courier New', Courier, monospace;
    }
    div[data-testid="stMetricLabel"] { color: #A0AEC0; font-weight: bold; }
    h1, h2, h3 { color: #FFFFFF !important; font-family: 'Arial', sans-serif; }
    </style>
    """, unsafe_allow_html=True)

# -------- LOAD AI MODEL --------
try:
    model = joblib.load("model.pkl")
except FileNotFoundError:
    st.error("🚨 model.pkl not found! Make sure it is in the exact same folder as this Python file.")
    st.stop()

# -------- SETTINGS --------
MT5_SYMBOLS = ["EURUSD", "GBPUSD", "XAUUSD"] 
CRYPTO_SYMBOLS = ["BTC/USDT", "ETH/USDT"]    
TIMEFRAME = mt5.TIMEFRAME_M5

# -------- INIT --------
if not mt5.initialize():
    st.error("MT5 not connected")
    st.stop()

exchange = ccxt.binance()

st.title("🧠 AI PRO Trading Terminal")
st.divider()

# -------- ACCOUNT INFO (MT5) --------
account = mt5.account_info()
col1, col2, col3 = st.columns(3)
col1.metric("MT5 Balance", f"${account.balance:.2f}")
col2.metric("MT5 Equity", f"${account.equity:.2f}")
col3.metric("MT5 Open Trades", mt5.positions_total())
st.divider()

# -------- DATA & INDICATOR FUNCTIONS --------
def calculate_indicators(df):
    # Features for your ML model
    df['ma_fast'] = df['close'].rolling(20).mean()
    df['ma_slow'] = df['close'].rolling(50).mean()
    
    # Calculate 14-period RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # Drop rows with NaN values so we don't feed garbage to the AI
    df.dropna(inplace=True)
    return df

def get_mt5_data(symbol):
    # Pulled 150 candles so we still have 100 left after calculating indicators
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, 150) 
    if rates is None: return None
    df = pd.DataFrame(rates)
    if df.empty: return None
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return calculate_indicators(df)

def get_crypto_data(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=150)
        df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        return calculate_indicators(df)
    except Exception as e:
        return None

# -------- AI PREDICTION FUNCTION --------
def get_signal(df):
    # Grab the very last row of data (the current live candle)
    last = df.iloc[-1]
    
    # Extract the three features your model needs
    current_rsi = last['rsi']
    current_ma_fast = last['ma_fast']
    current_ma_slow = last['ma_slow']
    
    # Feed it to the AI
    features = np.array([current_rsi, current_ma_fast, current_ma_slow]).reshape(1, -1)
    prediction = model.predict(features)

    if prediction[0] == 1:
        return "BUY"
    else:
        return "SELL"

# -------- CHART GRID --------
ALL_SYMBOLS = MT5_SYMBOLS + CRYPTO_SYMBOLS
cols = st.columns(len(ALL_SYMBOLS))

for i, symbol in enumerate(ALL_SYMBOLS):
    with cols[i]:
        st.subheader(symbol)

        if "/" in symbol:
            df = get_crypto_data(symbol)
        else:
            df = get_mt5_data(symbol)

        if df is None or df.empty:
            st.warning("No data")
            continue

        # Get signal from your AI Model
        signal = get_signal(df)

        if signal == "BUY":
            st.success("🟢 AI SIGNAL: BUY")
        elif signal == "SELL":
            st.error("🔴 AI SIGNAL: SELL")

        # -------- STYLED CHART --------
        fig = go.Figure()
        
        fig.add_trace(go.Candlestick(
            x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
            increasing_line_color='#00FFAA', increasing_fillcolor='#00FFAA', 
            decreasing_line_color='#FF3366', decreasing_fillcolor='#FF3366'  
        ))
        
        # Draw the updated MAs
        fig.add_trace(go.Scatter(x=df['time'], y=df['ma_fast'], name="MA Fast", line=dict(color='#00BFFF', width=1.5)))
        fig.add_trace(go.Scatter(x=df['time'], y=df['ma_slow'], name="MA Slow", line=dict(color='#FFD700', width=1.5)))
        
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor='rgba(0,0,0,0)', 
            plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False,
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=True, gridcolor='#333333', zeroline=False)
        )
        fig.update_xaxes(rangeslider_visible=False)

        st.plotly_chart(fig, use_container_width=True)

# -------- TIMESTAMP --------
st.divider()
st.caption(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
