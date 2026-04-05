import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import joblib
import numpy as np
import os

from config import SYMBOLS, CONFIDENCE_THRESHOLD, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER

try:
    from mt5_file_bridge import MT5FileBridge
    mt5 = MT5FileBridge()
except Exception as _e:
    st.error(f"Cannot load MT5 file bridge: {_e}")
    st.stop()

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

# -------- LOAD MODELS (one per symbol) --------
models = {}
for symbol in SYMBOLS:
    model_file = f"{symbol}_model.pkl"
    if os.path.exists(model_file):
        models[symbol] = joblib.load(model_file)
    else:
        st.warning(f"No model file for {symbol} ({model_file}). Train models first.")

# -------- INIT MT5 --------
try:
    _ok = mt5.initialize(
        "C:/Program Files/MetaTrader 5/terminal64.exe",
        login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER,
        timeout=60000,
    )
except Exception as _e:
    st.error(f"MT5 initialize raised an exception: {_e}")
    st.stop()
else:
    if not _ok:
        try:
            _err = mt5.last_error()
        except Exception:
            _err = ("unknown", "could not retrieve error")
        st.error(f"MT5 initialize failed — code={_err[0]}, message='{_err[1]}'")
        st.stop()

st.title("AI PRO Trading Terminal")
st.divider()

# -------- ACCOUNT INFO --------
account = mt5.account_info()
col1, col2, col3 = st.columns(3)
col1.metric("Balance",     f"${account.balance:.2f}" if account else "—")
col2.metric("Equity",      f"${account.equity:.2f}"  if account else "—")
col3.metric("Open Trades", mt5.positions_total())
st.divider()

# -------- HELPER FUNCTIONS --------
def calculate_indicators(df):
    df = df.copy()
    df['ma_fast'] = df['close'].rolling(20).mean()
    df['ma_slow'] = df['close'].rolling(50).mean()
    delta = df['close'].diff()
    gain  = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs    = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    df.dropna(inplace=True)
    return df

def get_mt5_data(symbol, timeframe_str):
    timeframe = TIMEFRAME_MAP.get(timeframe_str, mt5.TIMEFRAME_M15)
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 150)
    if rates is None:
        return None
    df = pd.DataFrame(rates)
    if df.empty:
        return None
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return calculate_indicators(df)

def get_signal_and_confidence(symbol, df):
    if symbol not in models:
        return "N/A", 0.0
    model = models[symbol]
    last = df.iloc[-1]
    features = np.array([last['rsi'], last['ma_fast'], last['ma_slow']]).reshape(1, -1)
    proba      = model.predict_proba(features)[0]
    confidence = max(proba)
    prediction = model.predict(features)[0]
    if confidence < CONFIDENCE_THRESHOLD:
        return "WEAK", confidence
    return "BUY" if prediction == 1 else "SELL", confidence

def get_open_position(symbol):
    positions = mt5.positions_get(symbol=symbol)
    if positions is None or len(positions) == 0:
        return None
    return positions[0]

def get_recent_trades(symbol, n=5):
    history = mt5.history_deals_get(
        datetime(2000, 1, 1),
        datetime.now(),
        group=f"*{symbol}*",
    )
    if history is None or len(history) == 0:
        return pd.DataFrame()
    df = pd.DataFrame([d._asdict() for d in history])
    df = df[df['symbol'] == symbol].tail(n)
    return df[['time', 'type', 'volume', 'price', 'profit']].copy() if not df.empty else pd.DataFrame()

# -------- PER-SYMBOL TABS --------
tabs = st.tabs(list(SYMBOLS.keys()))

for tab, (symbol, cfg) in zip(tabs, SYMBOLS.items()):
    with tab:
        st.subheader(f"{symbol}  |  {cfg['timeframe']}")

        df = get_mt5_data(symbol, cfg["timeframe"])

        if df is None or df.empty:
            st.warning(f"No data available for {symbol}.")
            continue

        signal, confidence = get_signal_and_confidence(symbol, df)
        position = get_open_position(symbol)

        # -------- METRICS ROW --------
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Signal",     signal)
        m2.metric("Confidence", f"{confidence * 100:.1f}%")
        m3.metric("Open Trade", "YES" if position else "NO")
        if position:
            m4.metric("Unrealized P&L", f"${position.profit:.2f}")
        else:
            m4.metric("Unrealized P&L", "-")

        # -------- SIGNAL BADGE --------
        if signal == "BUY":
            st.success("AI SIGNAL: BUY")
        elif signal == "SELL":
            st.error("AI SIGNAL: SELL")
        elif signal == "WEAK":
            st.warning(f"Signal too weak (confidence={confidence:.2f}). No trade.")
        else:
            st.info(f"No model loaded for {symbol}.")

        # -------- CANDLESTICK CHART --------
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df['time'],
            open=df['open'], high=df['high'], low=df['low'], close=df['close'],
            increasing_line_color='#00FFAA', increasing_fillcolor='#00FFAA',
            decreasing_line_color='#FF3366', decreasing_fillcolor='#FF3366',
        ))
        fig.add_trace(go.Scatter(
            x=df['time'], y=df['ma_fast'], name="MA Fast",
            line=dict(color='#00BFFF', width=1.5)
        ))
        fig.add_trace(go.Scatter(
            x=df['time'], y=df['ma_slow'], name="MA Slow",
            line=dict(color='#FFD700', width=1.5)
        ))
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=True,
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=True, gridcolor='#333333', zeroline=False),
        )
        fig.update_xaxes(rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

        # -------- RECENT TRADE HISTORY --------
        st.markdown("**Recent Trade History**")
        recent = get_recent_trades(symbol)
        if recent.empty:
            st.caption("No completed trades found for this symbol.")
        else:
            recent['time'] = pd.to_datetime(recent['time'], unit='s')
            recent['type'] = recent['type'].map({0: "BUY", 1: "SELL"}).fillna(recent['type'])
            st.dataframe(recent, use_container_width=True)

# -------- TIMESTAMP --------
st.divider()
st.caption(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
