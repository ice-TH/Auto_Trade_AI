from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from src.data.base import Bar, TimeFrame
from src.analysis.equity_strategy import scan_equity_setup

def test_scan_equity_setup_rejects_earnings():
    # If earnings guard triggers, should return REJECTED_EARNINGS
    with patch("src.analysis.equity_strategy.is_near_earnings", return_value=(True, "Earnings Blackout")):
        res = scan_equity_setup("NVDA")
        assert res["status"] == "REJECTED_EARNINGS"
        assert res["recommended_direction"] == "NEUTRAL"
        assert res["requires_approval"] is True

def test_scan_equity_setup_demand_pullback_approved():
    base_time = datetime(2026, 3, 15, 14, 0, tzinfo=timezone.utc)
    # Mock daily bars showing an uptrend and a bounce off a Demand Base
    # Price is around 225.0, Demand zone is [220.0, 224.0]
    mock_bar = Bar("AAPL", TimeFrame.DAY, base_time, base_time, open=222.0, high=226.0, low=221.0, close=225.0, volume=1000000.0, is_confirmed=True)
    
    with patch("src.analysis.equity_strategy.MT5DataAdapter") as mock_adapter_cls, \
         patch("src.analysis.equity_strategy.is_near_earnings", return_value=(False, "Safe")), \
         patch("src.analysis.equity_strategy.calculate_atr", return_value=[{"value": 4.0}]), \
         patch("src.analysis.equity_strategy.calculate_ema", side_effect=[
             [{"value": 222.0}],  # EMA 20
             [{"value": 218.0}],  # EMA 50 (Bullish: EMA20 > EMA50)
         ]), \
         patch("src.analysis.equity_strategy.detect_demand_supply_zones") as mock_ds:
        
        mock_adapter = MagicMock()
        mock_adapter.is_connected = True
        mock_adapter.get_bars.return_value = [mock_bar] * 30
        mock_adapter_cls.return_value = mock_adapter

        mock_ds.return_value = {
            "demand_zones": [{
                "type": "DEMAND", "pattern": "DBR", "zone_high": 224.0, "zone_low": 220.0, "zone_mid": 222.0
            }],
            "supply_zones": [{
                "type": "SUPPLY", "pattern": "RBD", "zone_high": 245.0, "zone_low": 240.0, "zone_mid": 242.5
            }]
        }

        setup = scan_equity_setup("AAPL", adapter=mock_adapter)
        assert setup["status"] == "BUY_PULLBACK_BASE"
        assert setup["recommended_direction"] == "BUY"
        assert setup["holding_type"] == "SWING_HOLDING_ALLOWED"
        assert setup["rr_ratio"] >= 2.0
        assert setup["requires_approval"] is True
        assert setup["order_block_excluded"] is True

def test_scan_equity_setup_rejects_headroom():
    base_time = datetime(2026, 3, 15, 14, 0, tzinfo=timezone.utc)
    # Price is 225.0, but overhead supply is right at 227.0 (Headroom 2.0 < 1.5x ATR 4.0 = 6.0)
    mock_bar = Bar("AAPL", TimeFrame.DAY, base_time, base_time, open=222.0, high=226.0, low=221.0, close=225.0, volume=1000000.0, is_confirmed=True)
    
    with patch("src.analysis.equity_strategy.MT5DataAdapter") as mock_adapter_cls, \
         patch("src.analysis.equity_strategy.is_near_earnings", return_value=(False, "Safe")), \
         patch("src.analysis.equity_strategy.calculate_atr", return_value=[{"value": 4.0}]), \
         patch("src.analysis.equity_strategy.calculate_ema", side_effect=[
             [{"value": 222.0}],
             [{"value": 218.0}],
         ]), \
         patch("src.analysis.equity_strategy.detect_demand_supply_zones") as mock_ds:
        
        mock_adapter = MagicMock()
        mock_adapter.is_connected = True
        mock_adapter.get_bars.return_value = [mock_bar] * 30
        mock_adapter_cls.return_value = mock_adapter

        mock_ds.return_value = {
            "demand_zones": [{
                "type": "DEMAND", "pattern": "DBR", "zone_high": 225.0, "zone_low": 221.0, "zone_mid": 223.0
            }],
            "supply_zones": [{
                "type": "SUPPLY", "pattern": "RBD", "zone_high": 230.0, "zone_low": 227.0, "zone_mid": 228.5
            }]
        }

        setup = scan_equity_setup("AAPL", adapter=mock_adapter)
        assert setup["status"] == "REJECTED_NEAR_RESISTANCE"
        assert setup["recommended_direction"] == "NEUTRAL"
        assert "ห้ามซื้อชิดแนวต้าน" in setup["setup_reason"]
