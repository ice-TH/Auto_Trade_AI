from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

class TimeFrame(str, Enum):
    WEEK = "1W"
    DAY = "1D"
    H4 = "4h"
    H1 = "1h"
    M15 = "15m"
    M5 = "5m"
    M1 = "1m"

class DataStatus(str, Enum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    SIMULATION = "SIMULATION"
    HISTORICAL = "HISTORICAL"

class SessionType(str, Enum):
    REGULAR = "REGULAR"
    PRE_MARKET = "PRE_MARKET"
    POST_MARKET = "POST_MARKET"
    CLOSED = "CLOSED"

@dataclass
class Bar:
    symbol: str
    timeframe: TimeFrame
    open_time: datetime  # UTC
    close_time: datetime # UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_confirmed: bool   # True = closed bar, False = still forming/unconfirmed
    status: DataStatus = DataStatus.SIMULATION
    session: SessionType = SessionType.REGULAR

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "open_time": self.open_time.isoformat(),
            "close_time": self.close_time.isoformat(),
            "time": int(self.open_time.timestamp()), # For Lightweight Charts
            "open": round(self.open, 2),
            "high": round(self.high, 2),
            "low": round(self.low, 2),
            "close": round(self.close, 2),
            "volume": round(self.volume, 2),
            "is_confirmed": self.is_confirmed,
            "status": self.status.value,
            "session": self.session.value,
        }

class BaseDataAdapter(ABC):
    @abstractmethod
    def get_bars(self, symbol: str, timeframe: TimeFrame, limit: int = 150) -> List[Bar]:
        """Fetch historical candlestick bars for a symbol and timeframe."""
        pass

    @abstractmethod
    def get_latest_quote(self, symbol: str) -> Dict[str, Any]:
        """Get the latest snapshot quote (bid, ask, last, timestamp, status)."""
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """Return adapter operational status (is_connected, data_status, error_info)."""
        pass
