import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

from src.data.base import BaseDataAdapter, Bar, TimeFrame, DataStatus, SessionType
from src.execution.mt5_client import mt5_client

logger = logging.getLogger("mt5_adapter")

# Mapping of standard TimeFrame to MT5 timeframe constants
TIMEFRAME_MAP = {}
if MT5_AVAILABLE:
    TIMEFRAME_MAP = {
        TimeFrame.WEEK: mt5.TIMEFRAME_W1,
        TimeFrame.DAY: mt5.TIMEFRAME_D1,
        TimeFrame.H4: mt5.TIMEFRAME_H4,
        TimeFrame.H1: mt5.TIMEFRAME_H1,
        TimeFrame.M15: mt5.TIMEFRAME_M15,
        TimeFrame.M5: mt5.TIMEFRAME_M5,
        TimeFrame.M1: mt5.TIMEFRAME_M1,
    }


class MT5DataAdapter(BaseDataAdapter):
    """
    Data adapter fetching real market bars and quotes directly from
    the local MetaTrader 5 terminal (e.g. Exness Demo/Real).
    """

    def __init__(self):
        self.mt5_client = mt5_client

    def _ensure_connected(self) -> bool:
        if not self.mt5_client.is_connected:
            res = self.mt5_client.connect()
            return res.get("connected", False)
        return True

    def _resolve_symbol(self, symbol: str) -> Optional[str]:
        """
        Resolve standard US ticker to broker-specific symbol name.
        e.g., AAPL -> AAPL, AAPLm, AAPL.c, etc.
        """
        if not MT5_AVAILABLE:
            return None

        candidates = [symbol, f"{symbol}c", f"{symbol}m", f"{symbol}.c", f"{symbol}_i"]
        for cand in candidates:
            info = mt5.symbol_info(cand)
            if info is not None:
                if not info.visible:
                    mt5.symbol_select(cand, True)
                return cand
        return symbol

    def get_bars(self, symbol: str, timeframe: TimeFrame, limit: int = 150) -> List[Bar]:
        """
        Fetch OHLCV historical and live bars from MT5.
        """
        if not MT5_AVAILABLE:
            logger.warning("MetaTrader5 module not available.")
            return []

        if not self._ensure_connected():
            logger.warning("MT5 terminal is not connected.")
            return []

        mt5_tf = TIMEFRAME_MAP.get(timeframe)
        if mt5_tf is None:
            logger.error(f"Unsupported timeframe: {timeframe}")
            return []

        actual_symbol = self._resolve_symbol(symbol) or symbol
        rates = mt5.copy_rates_from_pos(actual_symbol, mt5_tf, 0, limit)
        if rates is None or len(rates) == 0:
            logger.warning(f"No rates returned for {actual_symbol} ({timeframe.value}) from MT5.")
            return []

        bars: List[Bar] = []
        total = len(rates)
        for idx, r in enumerate(rates):
            # r['time'] is in seconds UTC (MT5 broker time)
            bar_time = datetime.fromtimestamp(int(r["time"]), tz=timezone.utc)
            # The latest bar in progress is index total - 1
            is_confirmed = (idx < total - 1)

            # Estimate close time based on timeframe
            if timeframe == TimeFrame.WEEK:
                import datetime as dt
                close_time = bar_time + dt.timedelta(days=7)
            elif timeframe == TimeFrame.DAY:
                import datetime as dt
                close_time = bar_time + dt.timedelta(days=1)
            elif timeframe == TimeFrame.M5:
                import datetime as dt
                close_time = bar_time + dt.timedelta(minutes=5)
            elif timeframe == TimeFrame.M1:
                import datetime as dt
                close_time = bar_time + dt.timedelta(minutes=1)
            else: # M15
                import datetime as dt
                close_time = bar_time + dt.timedelta(minutes=15)

            bars.append(
                Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=bar_time,
                    close_time=close_time,
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=float(r["tick_volume"]),
                    is_confirmed=is_confirmed,
                    status=DataStatus.LIVE,
                    session=SessionType.REGULAR
                )
            )

        return bars

    def get_latest_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch real-time Bid, Ask, Spread quote from MT5.
        """
        if not self._ensure_connected():
            return {
                "symbol": symbol,
                "error": "MT5 terminal not connected",
                "status": "DISCONNECTED"
            }

        actual_symbol = self._resolve_symbol(symbol) or symbol
        quote = self.mt5_client.get_symbol_quote(actual_symbol)
        quote["base_symbol"] = symbol
        return quote

    def get_status(self) -> Dict[str, Any]:
        connected = self._ensure_connected()
        acc = self.mt5_client.account_info if connected else {}
        return {
            "adapter": "MT5DataAdapter",
            "connected": connected,
            "status": "LIVE" if connected else "DISCONNECTED",
            "account_login": acc.get("login"),
            "server": acc.get("server"),
            "is_demo": acc.get("is_demo", True)
        }
