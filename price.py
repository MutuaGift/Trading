from mt5linux import MetaTrader5 as mt5

mt5.initialize()

symbol = "EURUSD"

# get latest tick
tick = mt5.symbol_info_tick(symbol)

print("Bid:", tick.bid)
print("Ask:", tick.ask)

mt5.shutdown()