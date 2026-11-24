import pytest
from datetime import datetime, timezone, timedelta
from src.data.base import Bar, TimeFrame, DataStatus, SessionType
from src.backtest.engine import BacktestEngine, TradeRecord

def create_backtest_bars(symbol="NVDA", count=100, base_price=140.0):
    bars = []
    base_time = datetime(2025, 1, 1, 14, 30, tzinfo=timezone.utc)
    for i in range(count):
        # Create a wave pattern to trigger zones and bounces
        wave = 5.0 if (i % 15 < 7) else -5.0
        p = base_price + wave
        bars.append(Bar(
            symbol=symbol,
            timeframe=TimeFrame.DAY,
            open_time=base_time + timedelta(days=i),
            close_time=base_time + timedelta(days=i, hours=6, minutes=30),
            open=p - 0.5,
            high=p + 2.0,
            low=p - 2.0,
            close=p + 0.5,
            volume=800000.0,
            is_confirmed=True,
            status=DataStatus.SIMULATION,
            session=SessionType.REGULAR
        ))
    return bars

def test_backtest_engine_exness_spread_deduction():
    engine = BacktestEngine()
    # NVDA spread is $0.16 in config/symbols.yaml
    assert engine.get_symbol_spread("NVDA") == 0.16
    # GOOGL spread is $0.30 in config/symbols.yaml
    assert engine.get_symbol_spread("GOOGL") == 0.30

def test_backtest_engine_execution_and_split():
    from src.data.mock_adapter import MockDataAdapter
    adapter = MockDataAdapter()
    bars = adapter.get_bars("NVDA", TimeFrame.DAY, limit=180)
    engine = BacktestEngine()
    
    trades = engine.run_backtest("NVDA", bars, initial_capital_thb=3000.0, split_ratio=0.70)
    
    # We should have completed simulated trades
    assert len(trades) > 0
    # Every trade must have duration >= 0
    assert all(t.duration_days >= 0 for t in trades)
    # Check that Exness spread was deducted
    for t in trades:
        expected_spread_usd = 0.16 * t.shares
        assert abs(t.spread_cost_usd - expected_spread_usd) < 0.001
        assert t.sample_type in ["IN_SAMPLE", "OUT_OF_SAMPLE"]

def test_gap_stop_loss_slippage():
    # Construct a scenario where bar opens below SL
    engine = BacktestEngine()
    bars = create_backtest_bars("AAPL", count=50, base_price=200.0)
    # Force a gap down on bar 38
    bars[38].open = 180.0
    bars[38].low = 175.0
    bars[38].close = 178.0
    
    trades = engine.run_backtest("AAPL", bars, initial_capital_thb=3000.0)
    # Any trade caught in gap should fill at open price
    gap_trades = [t for t in trades if t.exit_reason == "GAP_STOP_LOSS"]
    for gt in gap_trades:
        assert gt.exit_price <= gt.stop_loss
