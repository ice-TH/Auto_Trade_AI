from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from src.data.base import Bar, TimeFrame
from src.analysis.gold_strategy import (
    calculate_fibonacci_retracement,
    check_fibo_confluence,
    clamp_zone_size,
    detect_trading_session,
    detect_demand_supply_zones,
    scan_gold_setup,
    MAX_GOLD_SL_USD,
    MIN_GOLD_RR_RATIO,
)


def test_fibo_confluence_tiers_golden_pullback_and_shallow_rejection():
    # UP impulse: 3558 -> 3679 (diff = 121)
    # 23.6% = 3650.44 | 38.2% = 3632.78 | 50.0% = 3618.50 | 61.8% = 3604.22 | 78.6% = 3583.89
    fib_up = calculate_fibonacci_retracement(3679.0, 3558.0, label="Minor", direction="UP")

    # 1. Shallow Demand @ [3652.81, 3665.82] (above 23.6% = 3650.44) -> NONE (has_ok_fibo=False)
    shallow = check_fibo_confluence(3665.82, 3652.81, fib_up)
    assert shallow["fibo_tier"] == "NONE"
    assert shallow["has_confluence"] is False
    assert shallow["has_ok_fibo"] is False

    # 2. Pullback Demand @ [3616.00, 3622.00] (contains 50.0% = 3618.50) -> TREND_PULLBACK (has_ok_fibo=True)
    pb_50 = check_fibo_confluence(3622.00, 3616.00, fib_up)
    assert pb_50["fibo_tier"] == "TREND_PULLBACK"
    assert pb_50["has_confluence"] is False
    assert pb_50["has_ok_fibo"] is True
    assert pb_50["fibo_target_level"] == 3618.50

    # 3. Zone between 50% and 61.8% [3606.00, 3612.00] -> No gap! Still TREND_PULLBACK
    pb_mid = check_fibo_confluence(3612.00, 3606.00, fib_up)
    assert pb_mid["fibo_tier"] == "TREND_PULLBACK"
    assert pb_mid["has_ok_fibo"] is True

    # 4. Golden Zone Demand @ [3595.00, 3603.00] -> GOLDEN_ZONE (has_confluence=True, has_ok_fibo=True)
    gz = check_fibo_confluence(3603.00, 3595.00, fib_up)
    assert gz["fibo_tier"] == "GOLDEN_ZONE"
    assert gz["has_confluence"] is True
    assert gz["has_ok_fibo"] is True


def test_directional_fibonacci_up_vs_down():
    # UP swing: 3600 -> 3650 (diff = 50). Retracing DOWN into discount: 65% OTE = 3650 - 32.5 = 3617.50
    fib_up = calculate_fibonacci_retracement(3650.0, 3600.0, label="Minor", direction="UP")
    assert fib_up["direction"] == "UP"
    assert fib_up["fibo_650"] == 3617.50
    assert fib_up["golden_zone_high"] == 3619.10
    assert fib_up["golden_zone_low"] == 3610.70

    # DOWN swing: 3650 -> 3600 (diff = 50). Retracing UP into premium: 65% OTE = 3600 + 32.5 = 3632.50
    fib_down = calculate_fibonacci_retracement(3650.0, 3600.0, label="Minor", direction="DOWN")
    assert fib_down["direction"] == "DOWN"
    assert fib_down["fibo_650"] == 3632.50
    assert fib_down["golden_zone_high"] == 3639.30
    assert fib_down["golden_zone_low"] == 3630.90


def test_edge_anchored_clamp_zone_size():
    # Demand zone [3600, 3610] with ATR=4 (max 6.0): bottom MUST stay anchored at 3600.0!
    d_top, d_bot = clamp_zone_size(3610.0, 3600.0, atr=4.0, max_atr_mult=1.5, zone_type="DEMAND")
    assert d_bot == 3600.0
    assert d_top == 3606.0

    # Supply zone [3600, 3610] with ATR=4 (max 6.0): top MUST stay anchored at 3610.0!
    s_top, s_bot = clamp_zone_size(3610.0, 3600.0, atr=4.0, max_atr_mult=1.5, zone_type="SUPPLY")
    assert s_top == 3610.0
    assert s_bot == 3604.0


def test_detect_trading_session():
    # 21:30 BKK is 14:30 UTC in November -> London (14:30 GMT) x New York (09:30 EST) Overlap
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


def test_detect_demand_supply_multi_bar_base_and_no_zombie_zones():
    base_time = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
    bars = []

    # 1. DBR #1 at [2634, 2638] with 2-candle base, LATER BROKEN by a crash to 2625, even though price recovers to 2660
    bars.append(Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=2650.0, high=2652.0, low=2635.0, close=2636.0, volume=100.0, is_confirmed=True))
    bars.append(Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=2636.0, high=2638.0, low=2634.0, close=2637.0, volume=50.0, is_confirmed=True))
    bars.append(Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=2637.0, high=2638.0, low=2635.0, close=2636.5, volume=50.0, is_confirmed=True))
    bars.append(Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=2636.5, high=2655.0, low=2636.0, close=2654.0, volume=200.0, is_confirmed=True))
    # Subsequent crash breaks below 2634 -> permanently kills DBR #1!
    bars.append(Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=2654.0, high=2654.0, low=2624.0, close=2625.0, volume=250.0, is_confirmed=True))

    # 2. Fresh DBR #2 at [2624, 2627] with 2-candle base that holds cleanly
    bars.append(Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=2625.0, high=2627.0, low=2624.0, close=2626.0, volume=60.0, is_confirmed=True))
    bars.append(Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=2626.0, high=2627.0, low=2624.5, close=2626.5, volume=60.0, is_confirmed=True))
    bars.append(Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=2626.5, high=2662.0, low=2626.0, close=2660.0, volume=300.0, is_confirmed=True))

    for _ in range(12):
        bars.append(Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=2658.0, high=2660.0, low=2656.0, close=2659.0, volume=80.0, is_confirmed=True))

    zones = detect_demand_supply_zones(bars, min_bars=10)
    demands = zones["demand_zones"]
    assert len(demands) >= 1
    # Zombie zone #1 (low 2634) must NOT exist; only fresh zone #2 (low 2624) remains
    assert all(d["zone_low"] != 2634.0 for d in demands)
    assert any(d["zone_low"] == 2624.0 and d["base_candles"] == 2 for d in demands)


def test_unconfirmed_live_wick_does_not_false_trigger_market_buy():
    """If closed bar [-2] had NO rejection wick, an unconfirmed live wick on [-1] must NOT fire BUY_DEMAND_ZONE Market order."""
    london_time = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
    closed_bar = Bar("XAUUSD", TimeFrame.M5, london_time, london_time, open=3618.0, high=3618.2, low=3617.0, close=3617.0, volume=100.0, is_confirmed=True)
    # Live forming bar [-1] has temporary lower wick, but is_confirmed=False!
    live_bar = Bar("XAUUSD", TimeFrame.M5, london_time, london_time, open=3617.0, high=3618.0, low=3615.0, close=3617.5, volume=50.0, is_confirmed=False)

    with patch("src.analysis.gold_strategy.MT5DataAdapter") as mock_adapter_cls, \
         patch("src.analysis.gold_strategy.calculate_atr", return_value=[{"value": 3.0}]), \
         patch("src.analysis.gold_strategy.detect_demand_supply_zones") as mock_ds, \
         patch("src.analysis.gold_strategy.build_sr_zones", return_value=[]):

        mock_adapter = MagicMock()
        mock_adapter.is_connected = True
        mock_adapter._resolve_symbol.return_value = "XAUUSDm"
        mock_adapter.get_bars.return_value = [closed_bar] * 19 + [live_bar]
        mock_adapter_cls.return_value = mock_adapter

        mock_ds.return_value = {
            "demand_zones": [{"type": "DEMAND", "pattern": "DBR", "zone_high": 3618.0, "zone_low": 3615.0, "zone_mid": 3616.5}],
            "supply_zones": [{"type": "SUPPLY", "pattern": "RBD", "zone_high": 3635.0, "zone_low": 3630.0, "zone_mid": 3632.5}],
        }

        setup = scan_gold_setup()
        # Must recommend LIMIT or WAITING_FOR_REJECTION, never premature MARKET BUY
        assert setup["status"] in ("ACTIONABLE_BUY_LIMIT", "WAITING_FOR_REJECTION")
        assert setup["status"] != "BUY_DEMAND_ZONE"


def test_scan_gold_setup_runs():
    setup = scan_gold_setup()
    assert setup["symbol"] == "XAUUSD"
    assert setup["target_account"] in [434552387, 160219615]
    assert setup["order_block_excluded"] is True
    assert "session_info" in setup
    assert "trend_indicators" in setup
    assert "rr_ratio" in setup


def test_gold_strategy_rejects_poor_rr():
    base_time = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
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
            "demand_zones": [{"type": "DEMAND", "pattern": "DBR", "zone_high": 3618.0, "zone_low": 3616.0, "zone_mid": 3617.0}],
            "supply_zones": [{"type": "SUPPLY", "pattern": "RBD", "zone_high": 3630.0, "zone_low": 3625.0, "zone_mid": 3627.5}],
        }

        setup = scan_gold_setup()
        assert setup["status"] == "REJECTED_POOR_RR"
        assert setup["recommended_direction"] == "NEUTRAL"
        assert setup["rr_ratio"] < MIN_GOLD_RR_RATIO
        assert setup["pullback_entry_recommended"] is not None


def test_gold_strategy_rejects_wide_sl():
    base_time = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
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
            "demand_zones": [{"type": "DEMAND", "pattern": "DBR", "zone_high": 3618.0, "zone_low": 3610.0, "zone_mid": 3614.0}],
            "supply_zones": [{"type": "SUPPLY", "pattern": "RBD", "zone_high": 3650.0, "zone_low": 3645.0, "zone_mid": 3647.5}],
        }

        setup = scan_gold_setup()
        assert setup["status"] == "REJECTED_SL_TOO_WIDE"
        assert setup["recommended_direction"] == "NEUTRAL"
        assert setup["risk_usd"] > MAX_GOLD_SL_USD


def test_gold_strategy_accepts_sl_up_to_8_usd():
    base_time = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
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
            "demand_zones": [{"type": "DEMAND", "pattern": "DBR", "zone_high": 3618.0, "zone_low": 3613.5, "zone_mid": 3615.75}],
            "supply_zones": [{"type": "SUPPLY", "pattern": "RBD", "zone_high": 3640.0, "zone_low": 3635.0, "zone_mid": 3637.5}],
        }

        setup = scan_gold_setup()
        assert setup["status"] == "BUY_DEMAND_ZONE"
        assert setup["recommended_direction"] == "BUY"
        assert 6.00 < setup["risk_usd"] <= MAX_GOLD_SL_USD
        assert setup["risk_usd"] == 7.0
        assert setup["rr_ratio"] >= MIN_GOLD_RR_RATIO


def test_gold_strategy_m5_rejection_trigger_priority():
    base_time = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
    mock_bar_15m = Bar("XAUUSD", TimeFrame.M15, base_time, base_time, open=3618.0, high=3619.0, low=3617.0, close=3617.0, volume=100.0, is_confirmed=True)
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
            "demand_zones": [{"type": "DEMAND", "pattern": "DBR", "zone_high": 3618.0, "zone_low": 3615.0, "zone_mid": 3616.5}],
            "supply_zones": [{"type": "SUPPLY", "pattern": "RBD", "zone_high": 3635.0, "zone_low": 3630.0, "zone_mid": 3632.5}],
        }

        setup = scan_gold_setup()
        assert setup["status"] == "BUY_DEMAND_ZONE"
        assert setup["recommended_direction"] == "BUY"
        assert setup["trigger_timeframe"] == "M5"
        assert setup["m5_rejection_detected"] is True
        assert setup["recommended_sl"] == 3612.75
