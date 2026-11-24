import pytest
from datetime import datetime, timezone
from src.data.base import Bar, TimeFrame, DataStatus, SessionType
from src.analysis.indicators import calculate_ema, calculate_atr, calculate_volume_ma

def create_sample_bars(closes, highs=None, lows=None, volumes=None):
    bars = []
    base_time = datetime(2026, 1, 1, 14, 30, tzinfo=timezone.utc)
    for i, c in enumerate(closes):
        h = highs[i] if highs else c + 1.0
        l = lows[i] if lows else c - 1.0
        v = volumes[i] if volumes else 1000.0
        bars.append(Bar(
            symbol="TEST",
            timeframe=TimeFrame.DAY,
            open_time=base_time,
            close_time=base_time,
            open=c,
            high=h,
            low=l,
            close=c,
            volume=v,
            is_confirmed=True,
            status=DataStatus.SIMULATION,
            session=SessionType.REGULAR
        ))
    return bars

def test_calculate_ema():
    # 20 constant prices of 100 -> EMA should be 100
    bars = create_sample_bars([100.0] * 20)
    ema15 = calculate_ema(bars, period=15)
    assert len(ema15) == 6
    assert ema15[-1]["value"] == 100.0

def test_calculate_atr():
    # High = 105, Low = 95, Close = 100 for all -> TR = 10
    closes = [100.0] * 20
    highs = [105.0] * 20
    lows = [95.0] * 20
    bars = create_sample_bars(closes, highs, lows)
    atr = calculate_atr(bars, period=14)
    assert len(atr) > 0
    assert atr[-1]["value"] == 10.0

def test_calculate_volume_ma():
    volumes = [1000.0] * 25
    bars = create_sample_bars([100.0] * 25, volumes=volumes)
    vma = calculate_volume_ma(bars, period=20)
    assert len(vma) == 6
    assert vma[-1]["value"] == 1000.0
