import pytest
from datetime import datetime, timedelta, timezone
from src.data.base import Bar, TimeFrame, DataStatus, SessionType
from src.analysis.swings import detect_swings
from src.analysis.zones import build_sr_zones

def create_bars_with_pattern(highs, lows, closes):
    bars = []
    start = datetime(2026, 1, 1, 14, 30, tzinfo=timezone.utc)
    for i in range(len(highs)):
        t_open = start + timedelta(days=i)
        t_close = t_open + timedelta(hours=6, minutes=30)
        bars.append(Bar(
            symbol="TEST",
            timeframe=TimeFrame.DAY,
            open_time=t_open,
            close_time=t_close,
            open=closes[i],
            high=highs[i],
            low=lows[i],
            close=closes[i],
            volume=500000.0,
            is_confirmed=True,
            status=DataStatus.SIMULATION,
            session=SessionType.REGULAR
        ))
    return bars

def test_pivot_fractal_zero_lookahead():
    # Peak at index 3: Highs: [10, 12, 14, 20, 13, 11, 9]
    highs = [10.0, 12.0, 14.0, 20.0, 13.0, 11.0, 9.0]
    lows = [8.0, 10.0, 12.0, 18.0, 11.0, 9.0, 7.0]
    closes = [9.0, 11.0, 13.0, 19.0, 12.0, 10.0, 8.0]
    
    bars = create_bars_with_pattern(highs, lows, closes)
    swings = detect_swings(bars, n=3)
    
    high_swings = [s for s in swings if s.swing_type == "SWING_HIGH"]
    assert len(high_swings) == 1
    s = high_swings[0]
    assert s.price == 20.0
    assert s.index == 3
    # The swing at index 3 is confirmed at index 3 + 3 = 6
    assert s.confirmed_time == bars[6].close_time

def test_zone_building_and_clustering():
    # Generate 35 bars with distinct swing high at 150
    highs = [100.0] * 35
    lows = [90.0] * 35
    closes = [95.0] * 35
    
    # Create swing high at index 10
    highs[10] = 150.0
    highs[9] = 130.0
    highs[8] = 120.0
    highs[7] = 110.0
    highs[11] = 130.0
    highs[12] = 120.0
    highs[13] = 110.0

    bars = create_bars_with_pattern(highs, lows, closes)
    zones = build_sr_zones("TEST", bars, n_fractal=3, atr_multiplier=0.5)
    
    assert len(zones) > 0
    res_zones = [z for z in zones if z.zone_type == "RESISTANCE"]
    assert len(res_zones) >= 1
    assert any(abs(z.price_mid - 150.0) < 5.0 for z in res_zones)
