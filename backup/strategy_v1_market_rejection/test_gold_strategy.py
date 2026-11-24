import pytest
from datetime import datetime, timezone
from src.data.base import Bar, TimeFrame, DataStatus, SessionType
from unittest.mock import patch, MagicMock
from src.analysis.gold_strategy import (
    detect_trading_session,
    detect_demand_supply_zones,
    scan_gold_setup,
    MAX_GOLD_SL_USD,
    MIN_GOLD_RR_RATIO
)

def test_detect_trading_session():
    # 21:30 BKK is 14:30 UTC -> London x New York Overlap
    overlap_utc = datetime(2026, 11, 23, 14, 30, tzinfo=timezone.utc)
    res = detect_trading_session(overlap_utc)
    assert res["is_overlap"] is True
    assert res["liquidity_status"] == "PEAK_OVERLAP"
    assert "New York (อเมริกา)" in res["active_sessions"]
    assert "London (ยุโรป)" in res["active_sessions"]

    # 08:00 BKK is 01:00 UTC -> Tokyo / Sydney session
    asia_utc = datetime(2026, 11, 23, 1, 0, tzinfo=timezone.utc)
    res_asia = detect_trading_session(asia_utc)
    assert res_asia["is_overlap"] is False
    assert "Tokyo (เอเชีย)" in res_asia["active_sessions"]

def test_detect_demand_supply_zones():
    base_time = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
    bars = []
    
    # 1. Simulate a DBR (Drop-Base-Rally) Demand Zone
    # Leg 1: Drop
    bars.append(Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=2650.0, high=2652.0, low=2635.0, close=2636.0, volume=100.0, is_confirmed=True))
    # Base
    bars.append(Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=2636.0, high=2638.0, low=2634.0, close=2637.0, volume=50.0, is_confirmed=True))
    # Leg 2: Rally
    bars.append(Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=2637.0, high=2660.0, low=2636.0, close=2658.0, volume=200.0, is_confirmed=True))

    # Add extra filler bars to reach min_bars
    for i in range(15):
        bars.append(Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=2655.0, high=2658.0, low=2654.0, close=2656.0, volume=80.0, is_confirmed=True))

    zones = detect_demand_supply_zones(bars, min_bars=10)
    assert "demand_zones" in zones
    assert "supply_zones" in zones
    assert len(zones["demand_zones"]) >= 1
    assert zones["demand_zones"][0]["pattern"] in ["DBR", "RBR"]

def test_scan_gold_setup_runs():
    setup = scan_gold_setup()
    assert setup["symbol"] == "XAUUSD"
    assert setup["target_account"] in [434552387, 160219615]
    assert setup["order_block_excluded"] is True
    assert "session_info" in setup
    assert "trend_indicators" in setup
    assert "rr_ratio" in setup
    assert "risk_usd" in setup
    assert "reward_usd" in setup

def test_gold_strategy_rejects_poor_rr():
    base_time = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
    # Price close = 3617.5 is inside zone [3616, 3618], with rejection lower wick (low 3615 -> lower wick 2.0 / 3.0 = 66%)
    mock_bar = Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=3617.0, high=3618.0, low=3615.0, close=3617.5, volume=100.0, is_confirmed=True)
    
    with patch("src.analysis.gold_strategy.MT5DataAdapter") as mock_adapter_cls, \
         patch("src.analysis.gold_strategy.calculate_atr", return_value=[{"value": 4.0}]), \
         patch("src.analysis.gold_strategy.detect_demand_supply_zones") as mock_ds, \
         patch("src.analysis.gold_strategy.build_sr_zones", return_value=[]):
        
        mock_adapter = MagicMock()
        mock_adapter.is_connected = True
        mock_adapter._resolve_symbol.return_value = "XAUUSDm"
        mock_adapter.get_bars.return_value = [mock_bar] * 20
        mock_adapter_cls.return_value = mock_adapter

        mock_ds.return_value = {
            "demand_zones": [{
                "type": "DEMAND", "pattern": "DBR", "zone_high": 3618.0, "zone_low": 3616.0, "zone_mid": 3617.0
            }],
            "supply_zones": [{
                "type": "SUPPLY", "pattern": "RBD", "zone_high": 3630.0, "zone_low": 3625.0, "zone_mid": 3627.5
            }]
        }

        setup = scan_gold_setup()
        assert setup["status"] == "REJECTED_POOR_RR"
        assert setup["recommended_direction"] == "NEUTRAL"
        assert setup["rr_ratio"] < MIN_GOLD_RR_RATIO
        assert setup["pullback_entry_recommended"] is not None

def test_gold_strategy_rejects_wide_sl():
    base_time = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
    # Price close = 3617.5 is inside zone [3610, 3618], with rejection lower wick (low 3615 -> lower wick 2.0 / 3.0 = 66%)
    mock_bar = Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=3617.0, high=3618.0, low=3615.0, close=3617.5, volume=100.0, is_confirmed=True)
    
    with patch("src.analysis.gold_strategy.MT5DataAdapter") as mock_adapter_cls, \
         patch("src.analysis.gold_strategy.calculate_atr", return_value=[{"value": 4.0}]), \
         patch("src.analysis.gold_strategy.detect_demand_supply_zones") as mock_ds, \
         patch("src.analysis.gold_strategy.build_sr_zones", return_value=[]):
        
        mock_adapter = MagicMock()
        mock_adapter.is_connected = True
        mock_adapter._resolve_symbol.return_value = "XAUUSDm"
        mock_adapter.get_bars.return_value = [mock_bar] * 20
        mock_adapter_cls.return_value = mock_adapter

        # Demand zone low is 3610 (SL distance > $6.00)
        mock_ds.return_value = {
            "demand_zones": [{
                "type": "DEMAND", "pattern": "DBR", "zone_high": 3618.0, "zone_low": 3610.0, "zone_mid": 3614.0
            }],
            "supply_zones": [{
                "type": "SUPPLY", "pattern": "RBD", "zone_high": 3650.0, "zone_low": 3645.0, "zone_mid": 3647.5
            }]
        }

        setup = scan_gold_setup()
        assert setup["status"] == "REJECTED_SL_TOO_WIDE"
        assert setup["recommended_direction"] == "NEUTRAL"
        assert setup["risk_usd"] > MAX_GOLD_SL_USD

def test_gold_strategy_accepts_sl_up_to_8_usd():
    """Test that SL distance between $6.00 and $8.00 (e.g. $7.00) is accepted under the updated MAX_GOLD_SL_USD=8.00"""
    base_time = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
    # Price close = 3617.5, low = 3615.0 -> rejection lower wick 2.0 / 3.0 = 66%
    mock_bar = Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=3617.0, high=3618.0, low=3615.0, close=3617.5, volume=100.0, is_confirmed=True)

    with patch("src.analysis.gold_strategy.MT5DataAdapter") as mock_adapter_cls, \
         patch("src.analysis.gold_strategy.calculate_atr", return_value=[{"value": 4.0}]), \
         patch("src.analysis.gold_strategy.detect_demand_supply_zones") as mock_ds, \
         patch("src.analysis.gold_strategy.build_sr_zones", return_value=[]):

        mock_adapter = MagicMock()
        mock_adapter.is_connected = True
        mock_adapter._resolve_symbol.return_value = "XAUUSDm"
        mock_adapter.get_bars.return_value = [mock_bar] * 20
        mock_adapter_cls.return_value = mock_adapter

        # Demand zone low is 3613.5 -> raw_sl = 3613.5 - (4.0 * 0.75) = 3610.5 -> sl_distance = 3617.5 - 3610.5 = 7.0 USD
        # Supply at 3635 -> tp = 3635 - (4.0 * 0.35) = 3633.6 -> reward = 3633.6 - 3617.5 = 16.1 -> R:R = 16.1 / 7.0 = 2.30 >= 1.50
        mock_ds.return_value = {
            "demand_zones": [{
                "type": "DEMAND", "pattern": "DBR", "zone_high": 3618.0, "zone_low": 3613.5, "zone_mid": 3615.75
            }],
            "supply_zones": [{
                "type": "SUPPLY", "pattern": "RBD", "zone_high": 3640.0, "zone_low": 3635.0, "zone_mid": 3637.5
            }]
        }

        setup = scan_gold_setup()
        assert setup["status"] == "BUY_DEMAND_ZONE"
        assert setup["recommended_direction"] == "BUY"
        assert 6.00 < setup["risk_usd"] <= MAX_GOLD_SL_USD
        assert setup["risk_usd"] == 7.0
        assert setup["rr_ratio"] >= MIN_GOLD_RR_RATIO

def test_gold_strategy_waiting_for_rejection():
    """Test that price entering demand zone without rejection wick returns WAITING_FOR_REJECTION"""
    base_time = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
    # Candle with no lower wick (open=3618, close=3617, low=3617 -> lower_wick=0)
    mock_bar = Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=3618.0, high=3619.0, low=3617.0, close=3617.0, volume=100.0, is_confirmed=True)
    
    with patch("src.analysis.gold_strategy.MT5DataAdapter") as mock_adapter_cls, \
         patch("src.analysis.gold_strategy.calculate_atr", return_value=[{"value": 3.0}]), \
         patch("src.analysis.gold_strategy.detect_demand_supply_zones") as mock_ds, \
         patch("src.analysis.gold_strategy.build_sr_zones", return_value=[]):
        
        mock_adapter = MagicMock()
        mock_adapter.is_connected = True
        mock_adapter._resolve_symbol.return_value = "XAUUSDm"
        mock_adapter.get_bars.return_value = [mock_bar] * 20
        mock_adapter_cls.return_value = mock_adapter

        mock_ds.return_value = {
            "demand_zones": [{
                "type": "DEMAND", "pattern": "DBR", "zone_high": 3618.0, "zone_low": 3615.0, "zone_mid": 3616.5
            }],
            "supply_zones": [{
                "type": "SUPPLY", "pattern": "RBD", "zone_high": 3640.0, "zone_low": 3635.0, "zone_mid": 3637.5
            }]
        }

        setup = scan_gold_setup()
        assert setup["status"] == "WAITING_FOR_REJECTION"
        assert setup["recommended_direction"] == "NEUTRAL"
        assert "WAITING_FOR_REJECTION" in setup["status"]

def test_gold_strategy_approves_valid_setup():
    base_time = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
    # Candle with strong lower rejection wick: low=3615.0, open=3617.0, close=3617.5, high=3618.0 -> lower wick = 2.0 / 3.0 = 66%
    mock_bar = Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=3617.0, high=3618.0, low=3615.0, close=3617.5, volume=100.0, is_confirmed=True)
    
    with patch("src.analysis.gold_strategy.MT5DataAdapter") as mock_adapter_cls, \
         patch("src.analysis.gold_strategy.calculate_atr", return_value=[{"value": 3.0}]), \
         patch("src.analysis.gold_strategy.detect_demand_supply_zones") as mock_ds, \
         patch("src.analysis.gold_strategy.build_sr_zones", return_value=[]):
        
        mock_adapter = MagicMock()
        mock_adapter.is_connected = True
        mock_adapter._resolve_symbol.return_value = "XAUUSDm"
        mock_adapter.get_bars.return_value = [mock_bar] * 20
        mock_adapter_cls.return_value = mock_adapter

        mock_ds.return_value = {
            "demand_zones": [{
                "type": "DEMAND", "pattern": "DBR", "zone_high": 3618.0, "zone_low": 3615.0, "zone_mid": 3616.5
            }],
            "supply_zones": [{
                "type": "SUPPLY", "pattern": "RBD", "zone_high": 3635.0, "zone_low": 3630.0, "zone_mid": 3632.5
            }]
        }

        setup = scan_gold_setup()
        assert setup["status"] == "BUY_DEMAND_ZONE"
        assert setup["recommended_direction"] == "BUY"
        assert setup["rr_ratio"] >= MIN_GOLD_RR_RATIO
        assert setup["risk_usd"] <= MAX_GOLD_SL_USD
        assert setup["trigger_timeframe"] in ["M5", "15m"]

def test_gold_strategy_m5_rejection_trigger_priority():
    """Test that M5 candle rejection activates the trigger even if M15 hasn't closed with a wick yet"""
    base_time = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
    # M15 candle has no lower wick (open=3618, close=3617, low=3617 -> lower_wick=0)
    mock_bar_15m = Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=3618.0, high=3619.0, low=3617.0, close=3617.0, volume=100.0, is_confirmed=True)
    # M5 candle has strong lower rejection wick: low=3615.0, open=3617.0, close=3617.5, high=3618.0 -> lower wick = 2.0 / 3.0 = 66%
    mock_bar_5m = Bar("XAUUSD", TimeFrame.M5, base_time, base_time, open=3617.0, high=3618.0, low=3615.0, close=3617.5, volume=50.0, is_confirmed=True)

    with patch("src.analysis.gold_strategy.MT5DataAdapter") as mock_adapter_cls, \
         patch("src.analysis.gold_strategy.calculate_atr", return_value=[{"value": 3.0}]), \
         patch("src.analysis.gold_strategy.detect_demand_supply_zones") as mock_ds, \
         patch("src.analysis.gold_strategy.build_sr_zones", return_value=[]):

        def fake_get_bars(sym, tf, limit=100):
            if tf == TimeFrame.M5:
                return [mock_bar_5m] * 20
            return [mock_bar_15m] * 20

        mock_adapter = MagicMock()
        mock_adapter.is_connected = True
        mock_adapter._resolve_symbol.return_value = "XAUUSDm"
        mock_adapter.get_bars.side_effect = fake_get_bars
        mock_adapter_cls.return_value = mock_adapter

        mock_ds.return_value = {
            "demand_zones": [{
                "type": "DEMAND", "pattern": "DBR", "zone_high": 3618.0, "zone_low": 3615.0, "zone_mid": 3616.5
            }],
            "supply_zones": [{
                "type": "SUPPLY", "pattern": "RBD", "zone_high": 3635.0, "zone_low": 3630.0, "zone_mid": 3632.5
            }]
        }

        setup = scan_gold_setup()
        assert setup["status"] == "BUY_DEMAND_ZONE"
        assert setup["recommended_direction"] == "BUY"
        assert setup["trigger_timeframe"] == "M5"
        assert setup["m5_rejection_detected"] is True
        # Structural SL: 3615.0 (zone_low) - (3.0 * 0.75) = 3612.75
        assert setup["recommended_sl"] == 3612.75

