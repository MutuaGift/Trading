# AI Trading Bot — Windows Native

An autonomous AI trading bot for MetaTrader 5 that uses machine learning (Logistic Regression, Random Forest, Gradient Boosting) to generate BUY/SELL signals for forex and gold pairs.

## Supported Symbols

| Symbol | Lot | SL (pips) | TP (pips) |
|--------|-----|-----------|-----------|
| EURUSD | 0.10 | 50 | 100 |
| XAUUSD | 0.01 | 100 | 200 |
| USDJPY | 0.01 | 50 | 100 |
| GBPUSD | 0.01 | 50 | 100 |

## Architecture

```
start.bat
    └── watchdog.py          Process manager (auto-restarts on crash)
            ├── real_bot.py  AI trading loop
            └── dashboard.py Streamlit web UI → http://localhost:8501

real_bot.py uses MetaTrader5 (native Windows library)
    → mt5.initialize() launches terminal64.exe automatically
```

## Quick Start

### 1. Prerequisites

- **MetaTrader 5** — install from your broker or [metatrader5.com](https://www.metatrader5.com)
- **Python 3.10+** — install from [python.org](https://python.org) (check "Add to PATH")

### 2. Configure credentials

Edit `config.py` and set your MT5 account details:

```python
MT5_LOGIN    = 12345678
MT5_PASSWORD = "your_password"
MT5_SERVER   = "YourBroker-Server"
```

### 3. Train models (first time only)

Open a terminal in the project folder:

```bat
python -m venv venv
venv\Scripts\pip install -r requirements.txt

:: Collect historical data (MT5 must be open and logged in)
venv\Scripts\python get_data.py

:: Train ML models for all 4 symbols
venv\Scripts\python train_model.py
```

This creates `EURUSD_model.pkl`, `XAUUSD_model.pkl`, `USDJPY_model.pkl`, `GBPUSD_model.pkl`.

### 4. Start the bot

```bat
start.bat
```

On first run `start.bat` automatically creates the venv and installs dependencies. The watchdog starts the bot and dashboard, then monitors both and restarts either if they crash.

To force-restart a running instance:

```bat
start.bat --force
```

Press **Ctrl-C** to stop everything cleanly.

### 5. Dashboard

Open **http://localhost:8501** in a browser to see live signals, candlestick charts, account metrics, and trade history per symbol.

## How It Works

1. **Data collection** (`get_data.py`) — fetches 10,000 M15 candles per symbol from MT5 and calculates RSI(14), MA20, MA50, and a 5-candle lookahead label.
2. **Training** (`train_model.py`) — tries Logistic Regression, Random Forest, and Gradient Boosting with 5-fold cross-validation; saves the best model per symbol as a `.pkl` file.
3. **Trading loop** (`real_bot.py`) — every 60 seconds:
   - Skips symbols with an open trade
   - Fetches the latest 100 candles and calculates indicators
   - Runs the ML model; if confidence ≥ 60% places a BUY or SELL order with SL/TP
   - Detects closed trades and sends a Windows desktop notification
4. **Watchdog** (`watchdog.py`) — monitors the bot and dashboard with exponential back-off restarts (30s → 60s → 120s … capped at 5 min).

## Configuration

All settings are in `config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `CONFIDENCE_THRESHOLD` | 0.60 | Minimum model confidence to place a trade |
| `LOOP_INTERVAL` | 60 | Seconds between market checks |
| `RESPECT_MARKET_HOURS` | True | Skip trading outside Forex hours (Sun 22:00 – Fri 22:00 UTC) |
| `MAGIC` | 123 | MT5 magic number to identify bot trades |
| `MAX_RECONNECT_ATTEMPTS` | 10 | MT5 reconnect retries before exit |

## File Structure

```
Trading/
├── start.bat          Windows launcher
├── watchdog.py        Process manager
├── real_bot.py        AI trading loop
├── dashboard.py       Streamlit web dashboard
├── config.py          All settings and credentials
├── train_model.py     ML model training
├── get_data.py        Historical data collection
├── notifier.py        Windows desktop notifications (plyer)
├── requirements.txt   Python dependencies
├── *_model.pkl        Trained models (one per symbol)
├── *_data.csv         Training datasets (one per symbol)
└── logs/
    ├── bot.log        General bot activity
    ├── trades.log     All trade open/close events
    ├── watchdog.log   Watchdog activity
    └── dashboard.log  Streamlit output
```

## Dependencies

```
MetaTrader5    Native Windows MT5 Python library
pandas         Data manipulation
numpy          Numerical operations
scikit-learn   ML models
joblib         Model serialisation
streamlit      Web dashboard
plotly         Interactive charts
plyer          Windows desktop notifications
```

Install: `venv\Scripts\pip install -r requirements.txt`
