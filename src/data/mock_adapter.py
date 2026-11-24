import yaml
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.data.base import BaseDataAdapter, Bar, TimeFrame, DataStatus, SessionType
from src.data.calendar_guard import (
    TZ_UTC, TZ_EASTERN, to_eastern, RTH_OPEN, RTH_CLOSE, get_bar_close_time
)

class MockDataAdapter(BaseDataAdapter):
    """
    Generates realistic, deterministic multi-timeframe OHLCV data for US Equities.
    Used for Phase 1 & 2 development, backtesting, and simulation before live credentials.
    """
    def __init__(self, symbols_config_path: Optional[Path] = None):
        if symbols_config_path is None:
            symbols_config_path = Path(__file__).resolve().parent.parent.parent / "config" / "symbols.yaml"
        
        self.symbols_config = {}
        if symbols_config_path.exists():
            with open(symbols_config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                self.symbols_config = data.get("symbols", {})
        
        self._bars_cache: Dict[str, Dict[TimeFrame, List[Bar]]] = {}
        self._generate_all_series()

    def _generate_all_series(self):
        """Pre-generate reproducible bars for all configured symbols."""
        for symbol, info in self.symbols_config.items():
            base_price = info.get("base_price_estimate", 150.0)
            self._bars_cache[symbol] = {
                TimeFrame.WEEK: self._generate_week_bars(symbol, base_price, count=100),
                TimeFrame.DAY: self._generate_day_bars(symbol, base_price, count=200),
                TimeFrame.M15: self._generate_m15_bars(symbol, base_price, days=15),
            }

    def _generate_day_bars(self, symbol: str, base_price: float, count: int = 200) -> List[Bar]:
        rng = random.Random(f"{symbol}_DAY_SEED_42")
        bars: List[Bar] = []
        
        # End at yesterday's close
        end_date = datetime.now(TZ_UTC).date()
        current_date = end_date - timedelta(days=int(count * 1.5))
        
        price = base_price * 0.85 # Start a bit lower to have trend
        daily_volatility = base_price * 0.018 # ~1.8% daily vol
        
        # Periodic wave to create distinct swings and support/resistance zones
        t = 0
        while len(bars) < count and current_date < end_date:
            # Skip weekends
            if current_date.weekday() < 5:
                t += 1
                cycle = math.sin(t / 8.0) * (base_price * 0.05) + math.cos(t / 19.0) * (base_price * 0.07)
                trend = (t / float(count)) * (base_price * 0.15)
                target_mid = base_price + cycle + trend
                
                noise = rng.gauss(0, daily_volatility * 0.5)
                c = target_mid + noise
                o = c - rng.gauss(0, daily_volatility * 0.3)
                h = max(o, c) + abs(rng.gauss(daily_volatility * 0.4, daily_volatility * 0.2))
                l = min(o, c) - abs(rng.gauss(daily_volatility * 0.4, daily_volatility * 0.2))
                vol = abs(rng.gauss(1500000, 400000))
                
                # Market hours: 09:30 ET
                open_et = datetime.combine(current_date, RTH_OPEN, tzinfo=TZ_EASTERN)
                open_utc = open_et.astimezone(TZ_UTC)
                close_utc = get_bar_close_time(open_utc, TimeFrame.DAY)
                
                bars.append(Bar(
                    symbol=symbol,
                    timeframe=TimeFrame.DAY,
                    open_time=open_utc,
                    close_time=close_utc,
                    open=round(o, 2),
                    high=round(h, 2),
                    low=round(l, 2),
                    close=round(c, 2),
                    volume=round(vol, 0),
                    is_confirmed=True,
                    status=DataStatus.SIMULATION,
                    session=SessionType.REGULAR
                ))
            current_date += timedelta(days=1)
            
        return bars

    def _generate_week_bars(self, symbol: str, base_price: float, count: int = 100) -> List[Bar]:
        rng = random.Random(f"{symbol}_WEEK_SEED_42")
        bars: List[Bar] = []
        
        end_date = datetime.now(TZ_UTC).date()
        # Find latest Monday
        monday = end_date - timedelta(days=end_date.weekday())
        current_monday = monday - timedelta(weeks=count)
        
        price = base_price * 0.75
        weekly_vol = base_price * 0.035
        
        for w in range(count):
            cycle = math.sin(w / 6.0) * (base_price * 0.08)
            trend = (w / float(count)) * (base_price * 0.25)
            target = base_price + cycle + trend
            
            c = target + rng.gauss(0, weekly_vol * 0.4)
            o = c - rng.gauss(0, weekly_vol * 0.3)
            h = max(o, c) + abs(rng.gauss(weekly_vol * 0.6, weekly_vol * 0.2))
            l = min(o, c) - abs(rng.gauss(weekly_vol * 0.6, weekly_vol * 0.2))
            vol = abs(rng.gauss(7500000, 1500000))
            
            open_et = datetime.combine(current_monday, RTH_OPEN, tzinfo=TZ_EASTERN)
            open_utc = open_et.astimezone(TZ_UTC)
            close_utc = get_bar_close_time(open_utc, TimeFrame.WEEK)
            
            bars.append(Bar(
                symbol=symbol,
                timeframe=TimeFrame.WEEK,
                open_time=open_utc,
                close_time=close_utc,
                open=round(o, 2),
                high=round(h, 2),
                low=round(l, 2),
                close=round(c, 2),
                volume=round(vol, 0),
                is_confirmed=True,
                status=DataStatus.SIMULATION,
                session=SessionType.REGULAR
            ))
            current_monday += timedelta(weeks=1)
            
        return bars

    def _generate_m15_bars(self, symbol: str, base_price: float, days: int = 15) -> List[Bar]:
        rng = random.Random(f"{symbol}_M15_SEED_42")
        bars: List[Bar] = []
        
        now_utc = datetime.now(TZ_UTC)
        start_date = (now_utc - timedelta(days=days)).date()
        curr_date = start_date
        
        # 15m intervals during RTH: 09:30 to 16:00 ET = 26 bars per day
        m15_vol = base_price * 0.003
        
        last_close = base_price
        # Align with the latest day close
        if symbol in self._bars_cache and TimeFrame.DAY in self._bars_cache[symbol] and self._bars_cache[symbol][TimeFrame.DAY]:
            last_close = self._bars_cache[symbol][TimeFrame.DAY][-1].close

        curr_price = last_close
        while curr_date <= now_utc.date():
            if curr_date.weekday() < 5:
                session_start = datetime.combine(curr_date, RTH_OPEN, tzinfo=TZ_EASTERN)
                for step in range(26):
                    bar_open_et = session_start + timedelta(minutes=15 * step)
                    bar_open_utc = bar_open_et.astimezone(TZ_UTC)
                    bar_close_utc = bar_open_utc + timedelta(minutes=15)
                    
                    if bar_open_utc > now_utc:
                        break
                        
                    delta = rng.gauss(0, m15_vol)
                    c = curr_price + delta
                    o = curr_price
                    h = max(o, c) + abs(rng.gauss(m15_vol * 0.4, m15_vol * 0.2))
                    l = min(o, c) - abs(rng.gauss(m15_vol * 0.4, m15_vol * 0.2))
                    vol = abs(rng.gauss(80000, 30000))
                    
                    is_closed = now_utc >= bar_close_utc
                    
                    bars.append(Bar(
                        symbol=symbol,
                        timeframe=TimeFrame.M15,
                        open_time=bar_open_utc,
                        close_time=bar_close_utc,
                        open=round(o, 2),
                        high=round(h, 2),
                        low=round(l, 2),
                        close=round(c, 2),
                        volume=round(vol, 0),
                        is_confirmed=is_closed,
                        status=DataStatus.SIMULATION,
                        session=SessionType.REGULAR
                    ))
                    curr_price = c
            curr_date += timedelta(days=1)
            
        return bars[-300:] # Keep recent 300 M15 bars

    def get_bars(self, symbol: str, timeframe: TimeFrame, limit: int = 150) -> List[Bar]:
        if symbol not in self._bars_cache:
            # Fallback for unknown symbol
            self._bars_cache[symbol] = {
                TimeFrame.WEEK: self._generate_week_bars(symbol, 100.0, 50),
                TimeFrame.DAY: self._generate_day_bars(symbol, 100.0, 100),
                TimeFrame.M15: self._generate_m15_bars(symbol, 100.0, 10),
            }
        series = self._bars_cache[symbol].get(timeframe, [])
        return series[-limit:]

    def get_latest_quote(self, symbol: str) -> Dict[str, Any]:
        day_bars = self.get_bars(symbol, TimeFrame.DAY, limit=1)
        if day_bars:
            last_price = day_bars[-1].close
        else:
            last_price = self.symbols_config.get(symbol, {}).get("base_price_estimate", 100.0)
            
        spread = 0.02
        return {
            "symbol": symbol,
            "last": round(last_price, 2),
            "bid": round(last_price - (spread / 2), 2),
            "ask": round(last_price + (spread / 2), 2),
            "spread": spread,
            "timestamp": datetime.now(TZ_UTC).isoformat(),
            "status": DataStatus.SIMULATION.value,
            "note": "Simulated real-time quote"
        }

    def get_status(self) -> Dict[str, Any]:
        return {
            "adapter": "MockDataAdapter",
            "is_connected": True,
            "data_status": DataStatus.SIMULATION.value,
            "tracked_symbols": list(self.symbols_config.keys()),
            "message": "Using simulated historical data until official Webull API credentials are configured"
        }
