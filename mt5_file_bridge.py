"""
mt5_file_bridge.py — Drop-in replacement for mt5linux.MetaTrader5.

Uses a file-based command/response protocol with the mt5_bridge_ea.mq5 Expert
Advisor running inside the MT5 terminal.  Bypasses the MetaTrader5.dll IPC
(which fails under Wine) entirely.

Protocol files live in MQL5/Files/mt5bridge/ inside the MT5 installation:
  cmd.txt   — Python writes one command line, EA reads + deletes it
  resp.txt  — EA writes the response, Python reads + deletes it
"""

import time
from pathlib import Path

# ── Path to the MT5 portable data directory (MQL5/Files/) ────────────────────
_MT5_FILES_DIR = Path.home() / ".wine/drive_c/Program Files/MetaTrader 5/MQL5/Files"
_BRIDGE_DIR    = _MT5_FILES_DIR / "mt5bridge"
_CMD_FILE      = _BRIDGE_DIR / "cmd.txt"
_RESP_FILE     = _BRIDGE_DIR / "resp.txt"

_DEFAULT_TIMEOUT = 10.0   # seconds to wait for EA response
_POLL_INTERVAL   = 0.05   # seconds between polls


class MT5FileBridge:
    """
    File-based MetaTrader5 bridge.

    Provides the same API surface as mt5linux.MetaTrader5 (and the native
    MetaTrader5 Python module) that real_bot.py uses.
    """

    # ── MT5 constants (same integer values as native MetaTrader5 module) ──────
    TIMEFRAME_M1  = 1
    TIMEFRAME_M5  = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_M30 = 30
    TIMEFRAME_H1  = 16385
    TIMEFRAME_H4  = 16388
    TIMEFRAME_D1  = 16408

    ORDER_TYPE_BUY  = 0
    ORDER_TYPE_SELL = 1

    TRADE_ACTION_DEAL = 1

    ORDER_TIME_GTC = 0

    ORDER_FILLING_IOC = 1

    TRADE_RETCODE_DONE = 10009

    # ── Constructor ───────────────────────────────────────────────────────────
    def __init__(self):
        _BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
        self._last_error = (0, "OK")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _send(self, command: str, timeout: float = _DEFAULT_TIMEOUT) -> list:
        """
        Write a command line, wait for response, return list of response lines.
        Returns ["ERROR", code, message] on timeout or error.
        """
        # Remove any stale files from previous crashed sessions
        _CMD_FILE.unlink(missing_ok=True)
        _RESP_FILE.unlink(missing_ok=True)

        # Write command (EA reads this)
        _CMD_FILE.write_bytes(command.encode("ascii") + b"\n")

        # Wait for EA to write the response
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _RESP_FILE.exists():
                try:
                    raw  = _RESP_FILE.read_bytes()
                    _RESP_FILE.unlink(missing_ok=True)
                    text = raw.decode("ascii", errors="replace")
                    # Strip \r and trailing whitespace from each line
                    lines = [ln.rstrip("\r").rstrip() for ln in text.split("\n")]
                    return [ln for ln in lines if ln]  # remove empty
                except OSError:
                    pass  # file disappeared between exists() and read() — retry
            time.sleep(_POLL_INTERVAL)

        # Timed out — clean up
        _CMD_FILE.unlink(missing_ok=True)
        self._last_error = (-10005, "IPC timeout: EA did not respond")
        return ["ERROR", "-10005", "IPC timeout"]

    @staticmethod
    def _first_parts(lines: list) -> list:
        """Split the first response line on '|'."""
        return lines[0].split("|") if lines else ["ERROR"]

    # ── Public API ────────────────────────────────────────────────────────────

    def initialize(self, path=None, login=None, password=None,
                   server=None, timeout=None, portable=False) -> bool:
        """Connect to the running MT5 terminal via the bridge EA."""
        wait = max((timeout / 1000) if timeout else 30, 5)
        lines = self._send("INIT", timeout=wait)
        parts = self._first_parts(lines)
        if parts[0] == "OK":
            return True
        self._last_error = (int(parts[1]) if len(parts) > 1 else -1,
                            parts[2] if len(parts) > 2 else "Init failed")
        return False

    def shutdown(self) -> None:
        """No-op: the EA keeps running independently."""
        pass

    def last_error(self) -> tuple:
        """Return (error_code, error_description) for the last operation."""
        return self._last_error

    def terminal_info(self):
        """Return a simple object with terminal info, or None on failure."""
        lines = self._send("TERMINAL_INFO", timeout=5)
        parts = self._first_parts(lines)
        if parts[0] != "OK":
            return None
        # parts: OK|connected|trade_allowed|build|login|server
        connected     = parts[1] == "1" if len(parts) > 1 else True
        trade_allowed = parts[2] == "1" if len(parts) > 2 else True
        build         = int(parts[3]) if len(parts) > 3 else 0
        return _TerminalInfo(connected=connected,
                             trade_allowed=trade_allowed,
                             build=build)

    def positions_get(self, symbol: str = None):
        """Return list of open positions, optionally filtered by symbol."""
        cmd   = f"POSITIONS|{symbol or ''}"
        lines = self._send(cmd, timeout=8)
        parts = self._first_parts(lines)
        if parts[0] != "OK":
            return None

        positions = []
        for line in lines[1:]:
            if line == "END":
                break
            cols = line.split("|")
            if len(cols) < 8:
                continue
            positions.append(_Position(
                ticket     = int(cols[0]),
                symbol     = cols[1],
                type       = int(cols[2]),
                volume     = float(cols[3]),
                price_open = float(cols[4]),
                sl         = float(cols[5]),
                tp         = float(cols[6]),
                profit     = float(cols[7]),
                magic      = int(cols[8]) if len(cols) > 8 else 0,
            ))
        return positions

    def copy_rates_from_pos(self, symbol: str, timeframe: int,
                            pos: int, count: int):
        """
        Return a list of dicts (matching pd.DataFrame expectations) with
        columns: time, open, high, low, close, tick_volume.
        Returns None on failure.
        """
        cmd   = f"RATES|{symbol}|{timeframe}|{count}"
        lines = self._send(cmd, timeout=15)
        parts = self._first_parts(lines)
        if parts[0] != "OK":
            return None

        rows = []
        for line in lines[1:]:
            if line == "END":
                break
            cols = line.split("|")
            if len(cols) < 6:
                continue
            rows.append({
                "time":        int(cols[0]),
                "open":        float(cols[1]),
                "high":        float(cols[2]),
                "low":         float(cols[3]),
                "close":       float(cols[4]),
                "tick_volume": int(cols[5]),
                "spread":      int(cols[6]) if len(cols) > 6 else 0,
            })
        return rows if rows else None

    def symbol_info_tick(self, symbol: str):
        """Return current bid/ask tick for symbol, or None on failure."""
        lines = self._send(f"TICK|{symbol}", timeout=5)
        parts = self._first_parts(lines)
        if parts[0] != "OK" or len(parts) < 4:
            return None
        return _Tick(
            bid  = float(parts[1]),
            ask  = float(parts[2]),
            last = float(parts[3]),
            time = int(parts[4]) if len(parts) > 4 else 0,
        )

    def order_send(self, request: dict):
        """Send a trade request; return result object with retcode/order/comment."""
        action       = request.get("action",       self.TRADE_ACTION_DEAL)
        symbol       = request.get("symbol",       "")
        volume       = request.get("volume",       0.01)
        order_type   = request.get("type",         self.ORDER_TYPE_BUY)
        price        = request.get("price",        0.0)
        sl           = request.get("sl",           0.0)
        tp           = request.get("tp",           0.0)
        deviation    = request.get("deviation",    20)
        magic        = request.get("magic",        0)
        type_time    = request.get("type_time",    self.ORDER_TIME_GTC)
        type_filling = request.get("type_filling", self.ORDER_FILLING_IOC)

        cmd = (f"ORDER_SEND|{action}|{symbol}|{volume}|{order_type}|"
               f"{price}|{sl}|{tp}|{deviation}|{magic}|{type_time}|{type_filling}")
        lines = self._send(cmd, timeout=15)
        parts = self._first_parts(lines)

        if parts[0] == "OK":
            return _OrderResult(
                retcode = int(parts[1]) if len(parts) > 1 else self.TRADE_RETCODE_DONE,
                order   = int(parts[2]) if len(parts) > 2 else 0,
                comment = parts[3]      if len(parts) > 3 else "Done",
            )
        return _OrderResult(
            retcode = int(parts[1]) if len(parts) > 1 else -1,
            order   = 0,
            comment = parts[2] if len(parts) > 2 else "Error",
        )

    def symbol_select(self, symbol: str, enable: bool = True) -> bool:
        """Add (enable=True) or remove (enable=False) a symbol from Market Watch."""
        lines = self._send(f"SYMBOL_SELECT|{symbol}|{1 if enable else 0}", timeout=5)
        parts = self._first_parts(lines)
        return parts[0] == "OK"

    def account_info(self):
        """Return account info object with balance/equity/etc., or None on failure."""
        lines = self._send("ACCOUNT_INFO", timeout=5)
        parts = self._first_parts(lines)
        if parts[0] != "OK" or len(parts) < 9:
            return None
        return _AccountInfo(
            balance     = float(parts[1]),
            equity      = float(parts[2]),
            margin      = float(parts[3]),
            margin_free = float(parts[4]),
            profit      = float(parts[5]),
            login       = int(parts[6]),
            currency    = parts[7],
            leverage    = int(parts[8]),
            name        = parts[9] if len(parts) > 9 else "",
        )

    def positions_total(self) -> int:
        """Return count of currently open positions."""
        positions = self.positions_get()
        return len(positions) if positions is not None else 0

    def history_deals_get(self, date_from, date_to, group: str = None):
        """Return list of historical deals between date_from and date_to."""
        import calendar
        from_ts = int(calendar.timegm(date_from.timetuple()))
        to_ts   = int(calendar.timegm(date_to.timetuple()))
        lines   = self._send(f"HISTORY_DEALS|{from_ts}|{to_ts}", timeout=15)
        parts0  = self._first_parts(lines)
        if parts0[0] != "OK":
            return None

        deals = []
        for line in lines[1:]:
            if line == "END":
                break
            cols = line.split("|")
            if len(cols) < 7:
                continue
            sym = cols[1]
            if group and group.strip("*") not in sym:
                continue
            deals.append(_Deal(
                ticket = int(cols[0]),
                symbol = sym,
                type   = int(cols[2]),
                volume = float(cols[3]),
                price  = float(cols[4]),
                profit = float(cols[5]),
                time   = int(cols[6]),
            ))
        return deals if deals else None


# ── Simple namespace objects returned by the API ──────────────────────────────

class _TerminalInfo:
    __slots__ = ("connected", "trade_allowed", "build")
    def __init__(self, connected, trade_allowed, build):
        self.connected     = connected
        self.trade_allowed = trade_allowed
        self.build         = build


class _Position:
    __slots__ = ("ticket", "symbol", "type", "volume",
                 "price_open", "sl", "tp", "profit", "magic")
    def __init__(self, ticket, symbol, type, volume,
                 price_open, sl, tp, profit, magic=0):
        self.ticket     = ticket
        self.symbol     = symbol
        self.type       = type
        self.volume     = volume
        self.price_open = price_open
        self.sl         = sl
        self.tp         = tp
        self.profit     = profit
        self.magic      = magic


class _Tick:
    __slots__ = ("bid", "ask", "last", "time")
    def __init__(self, bid, ask, last, time):
        self.bid  = bid
        self.ask  = ask
        self.last = last
        self.time = time


class _OrderResult:
    __slots__ = ("retcode", "order", "comment")
    def __init__(self, retcode, order, comment):
        self.retcode = retcode
        self.order   = order
        self.comment = comment


class _AccountInfo:
    __slots__ = ("balance", "equity", "margin", "margin_free",
                 "profit", "login", "currency", "leverage", "name")
    def __init__(self, balance, equity, margin, margin_free,
                 profit, login, currency, leverage, name):
        self.balance     = balance
        self.equity      = equity
        self.margin      = margin
        self.margin_free = margin_free
        self.profit      = profit
        self.login       = login
        self.currency    = currency
        self.leverage    = leverage
        self.name        = name


class _Deal:
    __slots__ = ("ticket", "symbol", "type", "volume", "price", "profit", "time")
    def __init__(self, ticket, symbol, type, volume, price, profit, time):
        self.ticket = ticket
        self.symbol = symbol
        self.type   = type
        self.volume = volume
        self.price  = price
        self.profit = profit
        self.time   = time

    def _asdict(self):
        return {s: getattr(self, s) for s in self.__slots__}
