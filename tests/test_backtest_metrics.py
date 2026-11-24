import pytest
from datetime import datetime, timezone
from src.backtest.engine import TradeRecord
from src.backtest.metrics import BacktestMetrics

def create_mock_trades():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = TradeRecord(
        trade_id="T1", symbol="NVDA", sample_type="IN_SAMPLE",
        entry_time=now, exit_time=now, entry_price=140.0, exit_price=145.0,
        stop_loss=135.0, take_profit=145.0, shares=1, lot_size=0.01,
        gross_pnl_usd=5.0, spread_cost_usd=0.16, slippage_cost_usd=0.01, swap_cost_usd=0.03,
        net_pnl_usd=4.80, net_pnl_thb=168.0, duration_days=2, exit_reason="TAKE_PROFIT"
    )
    t2 = TradeRecord(
        trade_id="T2", symbol="NVDA", sample_type="IN_SAMPLE",
        entry_time=now, exit_time=now, entry_price=140.0, exit_price=135.0,
        stop_loss=135.0, take_profit=145.0, shares=1, lot_size=0.01,
        gross_pnl_usd=-5.0, spread_cost_usd=0.16, slippage_cost_usd=0.01, swap_cost_usd=0.03,
        net_pnl_usd=-5.20, net_pnl_thb=-182.0, duration_days=2, exit_reason="STOP_LOSS"
    )
    t3 = TradeRecord(
        trade_id="T3", symbol="GOOGL", sample_type="OUT_OF_SAMPLE",
        entry_time=now, exit_time=now, entry_price=175.0, exit_price=180.0,
        stop_loss=170.0, take_profit=180.0, shares=1, lot_size=0.01,
        gross_pnl_usd=5.0, spread_cost_usd=0.30, slippage_cost_usd=0.01, swap_cost_usd=0.05,
        net_pnl_usd=4.64, net_pnl_thb=162.4, duration_days=3, exit_reason="TAKE_PROFIT"
    )
    return [t1, t2, t3]

def test_backtest_metrics_calculation():
    trades = create_mock_trades()
    report = BacktestMetrics.calculate_full_report(trades, initial_capital_thb=3000.0)
    
    assert report["overall"]["total_trades"] == 3
    assert report["overall"]["win_trades"] == 2
    assert report["overall"]["loss_trades"] == 1
    assert report["overall"]["win_rate_percent"] == 66.7
    
    # Net profit: 168.0 - 182.0 + 162.4 = +148.4 THB
    assert abs(report["overall"]["net_profit_thb"] - 148.4) < 0.1
    assert report["final_equity_thb"] == 3148.4

def test_in_sample_out_sample_metrics_separation():
    trades = create_mock_trades()
    report = BacktestMetrics.calculate_full_report(trades, initial_capital_thb=3000.0)
    
    assert report["in_sample"]["total_trades"] == 2
    assert report["out_of_sample"]["total_trades"] == 1
    assert report["out_of_sample"]["win_rate_percent"] == 100.0
    assert "NVDA" in report["symbol_breakdown"]
    assert "GOOGL" in report["symbol_breakdown"]
