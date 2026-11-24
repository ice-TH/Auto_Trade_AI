import csv
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.data.base import BaseDataAdapter, Bar, TimeFrame, DataStatus, SessionType
from src.data.calendar_guard import TZ_UTC, get_bar_close_time

class CSVDataAdapter(BaseDataAdapter):
    """
    Adapter to load historical candlestick data from user-provided CSV files.
    """
    def __init__(self, data_directory: Optional[Path] = None):
        self.data_dir = data_directory or Path(__file__).resolve().parent.parent.parent / "data_store" / "csv_import"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Dict[TimeFrame, List[Bar]]] = {}

    def load_from_file(self, file_path: Path, symbol: str, timeframe: TimeFrame) -> List[Bar]:
        bars: List[Bar] = []
        if not file_path.exists():
            return bars
            
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    # Support multiple datetime formats
                    raw_dt = row.get("Date") or row.get("Datetime") or row.get("timestamp") or row.get("time")
                    if not raw_dt:
                        continue
                    
                    try:
                        dt = datetime.fromisoformat(raw_dt)
                    except ValueError:
                        dt = datetime.strptime(raw_dt, "%Y-%m-%d %H:%M:%S")
                        
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=TZ_UTC)
                        
                    o = float(row.get("Open") or row.get("open", 0))
                    h = float(row.get("High") or row.get("high", 0))
                    l = float(row.get("Low") or row.get("low", 0))
                    c = float(row.get("Close") or row.get("close", 0))
                    v = float(row.get("Volume") or row.get("volume", 0))
                    
                    close_time = get_bar_close_time(dt, timeframe)
                    bars.append(Bar(
                        symbol=symbol,
                        timeframe=timeframe,
                        open_time=dt,
                        close_time=close_time,
                        open=o,
                        high=h,
                        low=l,
                        close=c,
                        volume=v,
                        is_confirmed=True,
                        status=DataStatus.HISTORICAL,
                        session=SessionType.REGULAR
                    ))
                except Exception:
                    continue
                    
        bars.sort(key=lambda b: b.open_time)
        if symbol not in self._cache:
            self._cache[symbol] = {}
        self._cache[symbol][timeframe] = bars
        return bars

    def get_bars(self, symbol: str, timeframe: TimeFrame, limit: int = 150) -> List[Bar]:
        if symbol in self._cache and timeframe in self._cache[symbol]:
            return self._cache[symbol][timeframe][-limit:]
            
        file_path = self.data_dir / f"{symbol}_{timeframe.value}.csv"
        if file_path.exists():
            bars = self.load_from_file(file_path, symbol, timeframe)
            return bars[-limit:]
        return []

    def get_latest_quote(self, symbol: str) -> Dict[str, Any]:
        bars = self.get_bars(symbol, TimeFrame.DAY, limit=1)
        if bars:
            last = bars[-1].close
            return {
                "symbol": symbol,
                "last": last,
                "bid": last - 0.02,
                "ask": last + 0.02,
                "timestamp": bars[-1].open_time.isoformat(),
                "status": DataStatus.HISTORICAL.value,
                "note": "Imported from CSV"
            }
        return {"symbol": symbol, "error": "No CSV data found for symbol"}

    def get_status(self) -> Dict[str, Any]:
        return {
            "adapter": "CSVDataAdapter",
            "is_connected": True,
            "data_status": DataStatus.HISTORICAL.value,
            "import_dir": str(self.data_dir),
            "cached_symbols": list(self._cache.keys())
        }
