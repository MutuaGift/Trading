#!/usr/bin/env bash
set -e

echo "=== Starting MT5 Trading Bot Stack ==="

# 1. Launch MetaTrader 5 via Wine
echo "[1/4] Starting MetaTrader 5..."
wine "C:/Program Files/MetaTrader 5/terminal64.exe" &
sleep 5

# 2. Start the mt5linux bridge (Wine Python)
echo "[2/4] Starting mt5linux bridge..."
wine python -m mt5linux &
sleep 5

# 3. Start the AI trading bot
echo "[3/4] Starting real_bot.py..."
./venv/bin/python real_bot.py &
sleep 5

# 4. Launch the Streamlit dashboard
echo "[4/4] Starting Streamlit dashboard..."
./venv/bin/streamlit run dashboard.py

echo "=== All components started ==="
