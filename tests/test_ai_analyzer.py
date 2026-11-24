import pytest
from datetime import datetime, timezone
from src.data.base import Bar, TimeFrame, DataStatus, SessionType
from src.analysis.zones import SRZone
from src.analysis.ai_analyzer import analyze_market_narrative, generate_antigravity_prompt_context
from src.strategy.plans import TradingPlan, PlanStatus

def test_ai_narrative_generation():
    bars_d = [Bar(
        symbol="AAPL", timeframe=TimeFrame.DAY,
        open_time=datetime.now(timezone.utc), close_time=datetime.now(timezone.utc),
        open=225.0, high=230.0, low=224.0, close=228.0, volume=1000000.0,
        is_confirmed=True, status=DataStatus.SIMULATION, session=SessionType.REGULAR
    )] * 40
    
    zones = [
        SRZone(zone_id="Z1", symbol="AAPL", timeframe=TimeFrame.DAY, zone_type="SUPPORT", price_high=226.0, price_low=222.0, price_mid=224.0),
        SRZone(zone_id="Z2", symbol="AAPL", timeframe=TimeFrame.DAY, zone_type="RESISTANCE", price_high=245.0, price_low=240.0, price_mid=242.5)
    ]
    
    plan = TradingPlan(
        plan_id="TEST_P", symbol="AAPL", status=PlanStatus.READY_FOR_REVIEW,
        entry_price=228.0, stop_loss=220.0, take_profit=240.0,
        risk_reward_ratio=1.5, lot_size=0.01, shares=1
    )
    
    narrative = analyze_market_narrative("AAPL", [], bars_d, zones, plan)
    
    assert "macro_week_insight" in narrative
    assert "day_structure_insight" in narrative
    assert "headroom_insight" in narrative
    assert "actionable_verdict" in narrative
    assert "🎯 แผนพร้อมเข้าเทรด" in narrative["actionable_verdict"] or "QUALIFIED SETUP" in narrative["actionable_verdict"]

def test_antigravity_context_export():
    bars_d = [Bar(
        symbol="AAPL", timeframe=TimeFrame.DAY,
        open_time=datetime.now(timezone.utc), close_time=datetime.now(timezone.utc),
        open=225.0, high=230.0, low=224.0, close=228.0, volume=1000000.0,
        is_confirmed=True, status=DataStatus.SIMULATION, session=SessionType.REGULAR
    )]
    context = generate_antigravity_prompt_context("AAPL", bars_d, [], None)
    assert "AUTOTRADE MARKET CONTEXT FOR AAPL" in context
    assert "Antigravity, please evaluate" in context
