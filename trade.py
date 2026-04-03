from mt5linux import MetaTrader5 as mt5

def execute_trade(action, symbol="EURUSD", lot=0.01):
    # 1. Safely connect to MT5
    if not mt5.initialize():
        print("🚨 EXECUTION FAILED: MT5 not connected.")
        return False

    # 2. Force the symbol to be visible in Market Watch
    if not mt5.symbol_select(symbol, True):
        print(f"🚨 EXECUTION FAILED: {symbol} not found in Market Watch.")
        mt5.shutdown()
        return False

    # 3. Safely get the current price (Prevent the NoneType Crash)
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"🚨 EXECUTION FAILED: Could not get tick data for {symbol}. Is the market closed?")
        mt5.shutdown()
        return False

    # 4. Set up the order based on BUY or SELL
    if action.upper() == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
    elif action.upper() == "SELL":
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
    else:
        print(f"🚨 EXECUTION FAILED: Invalid action '{action}'")
        mt5.shutdown()
        return False

    # 5. Build the robust trade request
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "deviation": 10,
        "magic": 100,
        "comment": "Python AI Server",
        "type_time": mt5.ORDER_TIME_GTC,
        # Note: If your broker rejects this, change IOC to mt5.ORDER_FILLING_FOK
        "type_filling": mt5.ORDER_FILLING_IOC, 
    }

    # 6. Send the order and check the result
    result = mt5.order_send(request)
    
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"❌ TRADE REJECTED: {result.comment} (Error Code: {result.retcode})")
    else:
        print(f"✅ TRADE SUCCESS: {action} {lot} {symbol} at {price}")

    # Keep MT5 running in the background for the next trade
    # mt5.shutdown() # We remove this so the server doesn't disconnect after 1 trade!
    
    return True

# --- Quick Test ---
# If you run this file directly, it will test a BUY order.
if __name__ == "__main__":
    execute_trade("BUY")
