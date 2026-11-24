import pytest
from datetime import datetime, timezone, timedelta
from src.data.base import Bar, TimeFrame, DataStatus, SessionType
from src.analysis.zones import SRZone
from src.strategy.rules import evaluate_bounce_setup
from src.strategy.plans import PlanStatus
from config.settings import settings

def create_sample_bars(closes, highs=None, lows=None, tf=TimeFrame.DAY):
    bars = []
    base = datetime(2026, 1, 1, 14, 30, tzinfo=timezone.utc)
    for i, c in enumerate(closes):
        h = highs[i] if highs else c + 1.5
        l = lows[i] if lows else c - 1.5
        bars.append(Bar(
            symbol="TEST",
            timeframe=tf,
            open_time=base + timedelta(days=i),
            close_time=base + timedelta(days=i, hours=6),
            open=c,
            high=h,
            low=l,
            close=c,
            volume=500000.0,
            is_confirmed=True,
            status=DataStatus.SIMULATION,
            session=SessionType.REGULAR
        ))
    return bars

def test_headroom_guard_rejects_buying_into_resistance():
    # 40 bars closing around $100
    bars_d = create_sample_bars([100.0] * 40)
    
    # Active support at $98-$101
    sup = SRZone(
        zone_id="SUP_1", symbol="TEST", timeframe=TimeFrame.DAY,
        zone_type="SUPPORT", price_high=101.0, price_low=98.0, price_mid=99.5
    )
    # Active resistance VERY CLOSE at $101.5 - $103.0 (Headroom is only $1.5, which is < 1.0 ATR)
    res = SRZone(
        zone_id="RES_1", symbol="TEST", timeframe=TimeFrame.DAY,
        zone_type="RESISTANCE", price_high=103.0, price_low=101.5, price_mid=102.25
    )
    
    plan = evaluate_bounce_setup(
        symbol="TEST",
        bars_week=[],
        bars_day=bars_d,
        bars_m15=[],
        zones_day=[sup, res],
        settings=settings
    )
    
    # Must reject! Never buy into resistance
    assert plan.status == PlanStatus.REJECTED_NO_TRADE
    assert "Overhead Resistance" in plan.rejection_reason
    assert "Buying into resistance is strictly forbidden" in plan.rejection_reason

def test_valid_bounce_setup_headroom_open():
    bars_d = create_sample_bars([100.0] * 40)
    
    sup = SRZone(
        zone_id="SUP_1", symbol="TEST", timeframe=TimeFrame.DAY,
        zone_type="SUPPORT", price_high=101.0, price_low=98.0, price_mid=99.5
    )
    # Active resistance FAR ABOVE at $120.0 (Headroom is $20.0, very generous)
    res = SRZone(
        zone_id="RES_1", symbol="TEST", timeframe=TimeFrame.DAY,
        zone_type="RESISTANCE", price_high=122.0, price_low=120.0, price_mid=121.0
    )
    
    plan = evaluate_bounce_setup(
        symbol="TEST",
        bars_week=[],
        bars_day=bars_d,
        bars_m15=[],
        zones_day=[sup, res],
        settings=settings
    )
    
    # Since M15 bars are empty, status should be WAITING_CONDITIONS (waiting for M15 trigger)
    assert plan.status == PlanStatus.WAITING_CONDITIONS
    assert plan.headroom_to_resistance >= 15.0
    assert plan.stop_loss < 98.0 # SL below support
    assert plan.take_profit > 105.0 # TP near resistance
