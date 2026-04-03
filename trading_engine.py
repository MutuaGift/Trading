from mt5linux import MetaTrader5 as mt5
from config import *
from datetime import datetime

# ------------------ LOGGING ------------------
def log(message):
    print(f"{datetime.now().strftime('%H:%M:%S')} - {message}")
    with open("trades_log.txt", "a") as f:
        f.write(f"{datetime.now()} - {message}\n")

# ------------------ INIT ------------------
def initialize():
    if not mt5.initialize():
        log("🚨 MT5 initialization failed")
        return False
    return True

# ------------------ ACCOUNT ------------------
def get_balance():
    return mt5.account_info().balance

def calculate_lot(balance):
    # Dynamic risk management
    risk_amount = balance * (RISK_PERCENT / 100)
    lot = risk_amount / (STOP_LOSS_PIPS * 10)
    return max(round(lot, 2), 0.01)  # minimum lot protection

# ------------------ TRADE CHECK ------------------
def can_trade():
    positions = mt5.positions_get(symbol=SYMBOL)
    return positions is None or len(positions) == 0

# ------------------ PURE EXECUTION ------------------
def execute_trade(signal):
    """
    This function takes a 'BUY' or 'SELL' string and executes it safely.
    """
    if not initialize():
        return

    if not can_trade():
        log(f"🛡️ Trade skipped: {SYMBOL} position already open.")
        return

    # 1. Get exact market data
    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    
    if tick is None or info is None:
        log(f"🚨 FAILED: Could not get market data for {SYMBOL}. Market closed?")
        return

    # 2. Calculate dynamic lot size
    balance = get_balance()
    lot = calculate_lot(balance)

    # 3. Universal Pip Math (Works on Forex, Crypto, Metals)
    pip_value = 10 * info.point 

    if signal == "BUY":
        price = tick.ask
        sl = price - (STOP_LOSS_PIPS * pip_value)
        tp = price + (TAKE_PROFIT_PIPS * pip_value)
        order_type = mt5.ORDER_TYPE_BUY
    elif signal == "SELL":
        price = tick.bid
        sl = price + (STOP_LOSS_PIPS * pip_value)
        tp = price - (TAKE_PROFIT_PIPS * pip_value)
        order_type = mt5.ORDER_TYPE_SELL
    else:
        log(f"🚨 FAILED: Invalid signal received: {signal}")
        return

    # 4. Build the Request
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": 123456,
        "comment": "AI Bot Engine",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC, # Change to FOK if broker rejects
    }

    # 5. Send and Log
    result = mt5.order_send(request)
    
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log(f"❌ REJECTED: {signal} | Code: {result.retcode} | Msg: {result.comment}")
    else:
        log(f"✅ SUCCESS: {signal} | Lot:{lot} | Price:{price} | SL:{sl} | TP:{tp}")
