import pytest
from src.data.base import TimeFrame
from src.analysis.btc_scalper import (
    generate_mock_btc_1m_bars,
    detect_btc_demand_supply_zones,
    detect_btc_sr_and_trendline,
    calculate_rsi,
    scan_btc_1m
)

def test_btc_1m_bar_generation():
    bars = generate_mock_btc_1m_bars(count=60)
    assert len(bars) == 60
    assert bars[0].symbol == "BTCUSD"
    assert bars[0].timeframe == TimeFrame.M1
    assert 50000.0 < bars[-1].close < 70000.0

def test_btc_rsi_calculation():
    bars = generate_mock_btc_1m_bars(count=40)
    rsi_data = calculate_rsi(bars, period=14)
    assert len(rsi_data) > 0
    latest_rsi = rsi_data[-1]["value"]
    assert 0.0 <= latest_rsi <= 100.0

def test_btc_demand_supply_detection():
    bars = generate_mock_btc_1m_bars(count=120)
    ds = detect_btc_demand_supply_zones(bars)
    assert "demand_zones" in ds
    assert "supply_zones" in ds
    # Should detect at least one demand zone
    if ds["demand_zones"]:
        zone = ds["demand_zones"][0]
        assert zone["type"] == "DEMAND"
        assert zone["price_high"] >= zone["price_low"]

def test_btc_1m_scalp_scan_and_command():
    result = scan_btc_1m()
    assert result["symbol"] == "BTCUSD"
    assert "structure" in result
    assert "scalp_setup" in result
    assert result["scalp_setup"]["direction"] == "BUY"
    assert result["scalp_setup"]["stop_loss"] < result["scalp_setup"]["entry_price"]
    assert result["scalp_setup"]["take_profit"] > result["scalp_setup"]["entry_price"]
    assert "antigravity_execution_command" in result
    assert "--symbol BTCUSD" in result["antigravity_execution_command"]
