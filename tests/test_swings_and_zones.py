import pytest
from datetime import datetime, timedelta, timezone
from src.data.base import Bar, TimeFrame, DataStatus, SessionType
from src.analysis.swings import detect_swings, analyze_market_structure
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


def test_analyze_market_structure_hh_hl_and_choch_bear():
    # Build two ascending swing highs (120 -> 135) and two ascending swing lows (100 -> 112)
    # Using n_fractal=2 (5-bar window per pivot)
    closes = [
        108, 104, 100, 105, 110,  # SL1 = 100 at idx 2
        115, 120, 116, 113,       # SH1 = 120 at idx 6
        112, 115, 120, 125,       # SL2 = 112 at idx 9 (HL)
        130, 135, 128, 122, 118,  # SH2 = 135 at idx 14 (HH)
    ]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    bars_bull = create_bars_with_pattern(highs, lows, closes)

    st_bull = analyze_market_structure(bars_bull, n_fractal=2)
    assert st_bull["pattern"] == "HH/HL"
    assert st_bull["swing_bias"] == "BULLISH"
    assert st_bull["bias"] == "BULLISH"
    assert st_bull["live_break"] == "NONE"

    # Now append a bar that closes strictly below last confirmed Swing Low (111.0) -> CHOCH_BEAR
    closes_break = closes + [109.0]
    highs_break = [c + 1.0 for c in closes_break]
    lows_break = [c - 1.0 for c in closes_break]
    bars_choch = create_bars_with_pattern(highs_break, lows_break, closes_break)

    st_choch = analyze_market_structure(bars_choch, n_fractal=2)
    assert st_choch["pattern"] == "HH/HL"
    assert st_choch["live_break"] == "CHOCH_BEAR"
    assert st_choch["bias"] == "BEARISH"
