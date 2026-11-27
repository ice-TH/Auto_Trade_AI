from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from src.data.base import Bar, DataStatus, SessionType, TimeFrame
from src.execution.mt5_client import MT5Client
from src.analysis.gold_ai_context import build_gold_ai_context, summarize_candles
from src.execution.ai_trader_bridge import (
    _AI_LIMIT_RENEWALS,
    _seconds_to_next_m5_close,
    ai_modify_sltp,
    ai_place_limit,
    ai_place_market,
    validate_ai_gold_order,
    wait_for_trigger,
)


def _make_sample_bars(tf: TimeFrame, count: int = 45, start_price: float = 3560.0) -> list[Bar]:
    t0 = datetime(2026, 11, 25, 0, 0, tzinfo=timezone.utc)
    step_min = 5 if tf == TimeFrame.M5 else (15 if tf == TimeFrame.M15 else 60)
    bars: list[Bar] = []
    px = start_price
    for i in range(count):
        ot = t0 + timedelta(minutes=i * step_min)
        ct = ot + timedelta(minutes=step_min)
        o = px
        c = px + (0.8 if i % 2 == 0 else -0.5)
        h = max(o, c) + 1.2
        l = min(o, c) - 1.5
        bars.append(
            Bar(
                symbol="XAUUSDc",
                timeframe=tf,
                open_time=ot,
                close_time=ct,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=120.0 + i,
                is_confirmed=(i < count - 1),
                status=DataStatus.SIMULATION,
                session=SessionType.REGULAR,
            )
        )
        px = c
    return bars


def _peaceful_bridge_guards():
    return (
        patch("src.execution.ai_trader_bridge.is_news_blackout", return_value=(False, "Normal")),
        patch("src.execution.ai_trader_bridge.is_rollover_blackout", return_value=(False, "Normal")),
    )


def test_hard_risk_gate_enforces_cent_lot_sl_cap_rr_spread_and_single_position():
    cli = MT5Client()
    cli.is_connected = False
    cli.account_info = {"login": 160219615, "currency": "USC"}

    p_news, p_roll = _peaceful_bridge_guards()
    with p_news, p_roll:
        # 1. Valid order on Cent #160219615 locks symbol=XAUUSDc and volume=0.06
        ok = validate_ai_gold_order(
            order_kind="LIMIT",
            direction="BUY",
            entry_price=3560.0,
            sl_price=3554.0,   # $6.00 <= $8.00
            tp_price=3572.0,   # $12.00 -> R:R = 2.0 >= 1.50
            current_price=3563.0,
            spread=0.22,
            client=cli,
        )
        assert ok["valid"] is True
        assert ok["symbol"] == "XAUUSDc"
        assert ok["locked_volume"] == 0.06
        assert ok["rr_ratio"] == 2.0

        # 2. Rejects SL > $8.00
        bad_sl = validate_ai_gold_order("MARKET", "BUY", 3560.0, 3550.5, 3580.0, 3560.0, 0.22, client=cli)
        assert bad_sl["valid"] is False
        assert bad_sl["code"] == "REJECTED_SL_TOO_WIDE"

        # 3. Rejects R:R < 1.50
        bad_rr = validate_ai_gold_order("MARKET", "BUY", 3560.0, 3555.0, 3566.0, 3560.0, 0.22, client=cli)
        assert bad_rr["valid"] is False
        assert bad_rr["code"] == "REJECTED_POOR_RR"

        # 4. Rejects Spread > $0.40
        bad_sp = validate_ai_gold_order("MARKET", "BUY", 3560.0, 3555.0, 3570.0, 3560.0, 0.55, client=cli)
        assert bad_sp["valid"] is False
        assert bad_sp["code"] == "BLOCKED_SPREAD_GUARD"

        # 5. Rejects BUY_LIMIT at or above current price
        bad_lim = validate_ai_gold_order("LIMIT", "BUY", 3565.0, 3560.0, 3575.0, 3563.0, 0.22, client=cli)
        assert bad_lim["valid"] is False
        assert bad_lim["code"] == "INVALID_BUY_LIMIT_PRICE"

        # 6. Rejects when a Gold position is already open (Single-Position Guard)
        cli.simulated_positions = [{
            "ticket": 9001,
            "symbol": "XAUUSDc",
            "direction": "BUY",
            "volume": 0.06,
            "open_price": 3560.0,
            "current_price": 3562.0,
            "sl": 3555.0,
            "tp": 3570.0,
        }]
        dup = validate_ai_gold_order("MARKET", "BUY", 3562.0, 3557.0, 3572.0, 3562.0, 0.22, client=cli)
        assert dup["valid"] is False
        assert dup["code"] == "BLOCKED_SINGLE_POSITION"


def test_ai_place_limit_replaces_old_limit_and_modify_sltp_guards():
    cli = MT5Client()
    cli.is_connected = False
    cli.account_info = {"login": 160219615, "currency": "USC"}
    _AI_LIMIT_RENEWALS.clear()

    p_news, p_roll = _peaceful_bridge_guards()
    with p_news, p_roll:
        r1 = ai_place_limit(
            direction="BUY",
            price=3560.0,
            sl=3555.0,
            tp=3570.0,
            ttl_minutes=15,
            reason="First OTE limit",
            client=cli,
            current_price_override=3564.0,
            spread_override=0.20,
            save_chart=False,
        )
        assert r1["success"] is True
        first_ticket = r1["order"]["ticket"]
        assert len(cli.get_pending_orders("XAUUSDc")) == 1

        # Placing a second limit cleanly cancels/replaces the first one
        r2 = ai_place_limit(
            direction="BUY",
            price=3559.0,
            sl=3554.0,
            tp=3569.0,
            ttl_minutes=15,
            reason="Adjusted OTE limit",
            client=cli,
            current_price_override=3564.0,
            spread_override=0.20,
            save_chart=False,
        )
        assert r2["success"] is True
        assert first_ticket in r2["replaced_pending_tickets"]
        assert len(cli.get_pending_orders("XAUUSDc")) == 1

        # Market fill cancels remaining pending order
        mkt = ai_place_market(
            direction="BUY",
            sl=3558.0,
            tp=3572.0,
            reason="Confirmed M5 rejection",
            client=cli,
            price_override=3563.0,
            spread_override=0.20,
            save_chart=False,
        )
        assert mkt["success"] is True
        assert len(cli.get_pending_orders("XAUUSDc")) == 0
        pos_ticket = mkt["order"]["ticket"]

        # Modify SL/TP blocks widening risk > $8.00 or stripping SL
        open_px = cli.get_open_positions()[0]["open_price"]
        cli.simulated_positions[0]["current_price"] = open_px + 4.0
        bad_mod = ai_modify_sltp(pos_ticket, sl=open_px - 9.5, tp=open_px + 12.0, client=cli)
        assert bad_mod["success"] is False

        good_mod = ai_modify_sltp(pos_ticket, sl=open_px + 0.5, tp=open_px + 12.0, client=cli)
        assert good_mod["success"] is True


def test_context_and_base_anchored_chart_rendering(tmp_path: Path):
    cli = MT5Client()
    cli.is_connected = False
    cli.account_info = {"login": 160219615, "currency": "USC"}

    bars_h1 = _make_sample_bars(TimeFrame.H1, 20, 3555.0)
    bars_15m = _make_sample_bars(TimeFrame.M15, 60, 3558.0)
    bars_5m = _make_sample_bars(TimeFrame.M5, 45, 3562.0)

    sample_setup = {
        "status": "WAITING_FOR_REJECTION",
        "mt5_symbol": "XAUUSDc",
        "current_price": 3564.20,
        "spread": 0.22,
        "current_atr": 3.20,
        "live_bar_range": 1.80,
        "demand_zones": [{
            "type": "DEMAND",
            "pattern": "DBR",
            "timeframe": "15m",
            "zone_high": 3562.50,
            "zone_low": 3559.00,
            "zone_mid": 3560.75,
            "created_time": bars_15m[-12].open_time.isoformat(),
        }],
        "supply_zones": [{
            "type": "SUPPLY",
            "pattern": "RBD",
            "timeframe": "1H",
            "zone_high": 3575.00,
            "zone_low": 3571.00,
            "zone_mid": 3573.00,
            "created_time": bars_15m[-35].open_time.isoformat(),
        }],
        "nearest_demand": {
            "type": "DEMAND",
            "pattern": "DBR",
            "timeframe": "15m",
            "zone_high": 3562.50,
            "zone_low": 3559.00,
            "zone_mid": 3560.75,
            "created_time": bars_15m[-12].open_time.isoformat(),
        },
        "nearest_supply": {
            "type": "SUPPLY",
            "pattern": "RBD",
            "timeframe": "1H",
            "zone_high": 3575.00,
            "zone_low": 3571.00,
            "zone_mid": 3573.00,
            "created_time": bars_15m[-35].open_time.isoformat(),
        },
        "fibo_buy": {"fibo_650": 3561.20},
        "fibo_sell": {"fibo_650": 3572.40},
        "session_info": {"liquidity_status": "HIGH"},
        "trend_indicators": {"trend": "BULLISH", "h1_trend": "BULLISH"},
    }

    candles = summarize_candles(bars_5m, atr=2.0, limit=5)
    assert len(candles) == 5
    assert all("lower_wick_pct" in c and "upper_wick_pct" in c for c in candles)

    ctx = build_gold_ai_context(
        include_chart=True,
        event_tag="UNIT_TEST",
        planned_trade={"entry": 3561.20, "sl": 3556.50, "tp": 3570.50},
        note="Unit test chart verification",
        client=cli,
        setup_override=sample_setup,
        bars_override={"H1": bars_h1, "M15": bars_15m, "M5": bars_5m},
        base_screenshots_dir=tmp_path,
    )
    assert ctx["mode"] == "AI_TRADER_RAW_CONTEXT"
    assert len(ctx["raw_candles"]["M5_last_18"]) == 18
    img_file = Path(ctx["chart_artifacts"]["image_path"])
    json_file = Path(ctx["chart_artifacts"]["audit_json_path"])
    assert img_file.exists() and img_file.stat().st_size > 5000
    assert json_file.exists()


def test_wait_for_trigger_proximity_wakeup_sniper_wait_and_knife_guard():
    cli = MT5Client()
    cli.is_connected = False
    cli.account_info = {"login": 160219615, "currency": "USC"}

    zone_setup = {
        "mt5_symbol": "XAUUSDc",
        "current_price": 3563.50,  # within 0.8 * 3.0 ($2.40) of Demand 3562.00
        "current_atr": 3.00,
        "live_bar_range": 1.20,
        "spread": 0.20,
        "status": "WAITING_FOR_REJECTION",
        "nearest_demand": {"pattern": "DBR", "zone_low": 3559.00, "zone_high": 3562.00},
        "nearest_supply": None,
    }

    dummy_ctx = lambda **kwargs: {"dummy": True, "chart_requested": kwargs.get("include_chart")}
    p_news, p_roll = _peaceful_bridge_guards()
    with p_news, p_roll:
        # 1. Normal radar wakes IMMEDIATELY on ZONE_PROXIMITY without sleeping
        sleeps = []
        res_prox = wait_for_trigger(
            poll_sec=20.0,
            max_wait_sec=900.0,
            proximity_atr=0.80,
            sniper_m5=False,
            client=cli,
            setup_fn=lambda: zone_setup,
            context_fn=dummy_ctx,
            sleep_fn=lambda s: sleeps.append(s),
        )
        assert res_prox["wakeup_reason"] == "ZONE_PROXIMITY"
        assert len(sleeps) == 0
        assert res_prox["context"]["chart_requested"] is True
        assert len(cli.get_pending_orders()) == 0  # Watchdog never places orders!

        # 2. Sniper M5 mode does NOT immediately re-wake on the same zone; waits until max_wait_sec
        res_sniper = wait_for_trigger(
            poll_sec=0.05,
            max_wait_sec=0.08,
            sniper_m5=True,
            client=cli,
            setup_fn=lambda: zone_setup,
            context_fn=dummy_ctx,
        )
        assert res_sniper["wakeup_reason"] == "SNIPER_M5_BAR_CHECK"

        # 3. Falling Knife immediately cancels AI's Pending Buy Limit and wakes AI up!
        cli.send_limit_order("XAUUSDc", "BUY", 0.06, 3560.50, 3555.50, 3570.50)
        knife_setup = dict(zone_setup, status="REJECTED_FALLING_KNIFE")
        res_knife = wait_for_trigger(
            poll_sec=20.0,
            max_wait_sec=900.0,
            client=cli,
            setup_fn=lambda: knife_setup,
            context_fn=dummy_ctx,
        )
        assert res_knife["wakeup_reason"] == "LIMIT_EMERGENCY_CANCELLED"
        assert len(cli.get_pending_orders()) == 0

        # 4. Break-Even +1.0R auto-locks during radar cycle while holding an open position
        cli.simulated_positions = [{
            "ticket": 77701,
            "symbol": "XAUUSDc",
            "direction": "BUY",
            "volume": 0.06,
            "open_price": 3560.00,
            "current_price": 3565.50,  # +5.50 gain >= 1.0R ($5.00 risk)
            "sl": 3555.00,
            "tp": 3572.00,
        }]
        res_be = wait_for_trigger(
            poll_sec=0.05,
            max_wait_sec=0.05,
            client=cli,
            setup_fn=lambda: zone_setup,
            context_fn=dummy_ctx,
        )
        assert cli.simulated_positions[0]["sl"] > 3560.00
        assert any("Break-Even" in a for a in res_be["watchdog_actions"])


def test_limit_approaching_prefill_wakeup_guard_ticket_and_candidates():
    cli = MT5Client()
    cli.is_connected = False
    cli.account_info = {"login": 160219615, "currency": "USC"}

    # Wide $13.07 Demand zone ($3531.33 - $3544.40) with high ATR ($10.59) like real market case
    wide_zone_setup = {
        "mt5_symbol": "XAUUSDc",
        "current_price": 3550.00,
        "current_atr": 10.59,
        "live_bar_range": 1.40,
        "spread": 0.22,
        "status": "WAITING_FOR_ZONE",
        "demand_zones": [{
            "type": "DEMAND",
            "pattern": "DBR",
            "timeframe": "15m",
            "zone_low": 3531.33,
            "zone_high": 3544.40,
            "zone_mid": 3537.86,
        }],
        "supply_zones": [{
            "type": "SUPPLY",
            "pattern": "M15_RESISTANCE",
            "timeframe": "15m",
            "zone_low": 3566.78,
            "zone_high": 3577.44,
            "zone_mid": 3572.11,
        }],
        "nearest_demand": {
            "type": "DEMAND",
            "pattern": "DBR",
            "timeframe": "15m",
            "zone_low": 3531.33,
            "zone_high": 3544.40,
            "zone_mid": 3537.86,
        },
        "nearest_supply": {
            "type": "SUPPLY",
            "pattern": "M15_RESISTANCE",
            "timeframe": "15m",
            "zone_low": 3566.78,
            "zone_high": 3577.44,
            "zone_mid": 3572.11,
        },
        "fibo_buy": {"fibo_650": 3543.40},
        "fibo_sell": {"fibo_650": 3572.00},
    }

    bars_5m = _make_sample_bars(TimeFrame.M5, 20, 3548.0)
    p_news, p_roll = _peaceful_bridge_guards()
    with p_news, p_roll:
        ctx = build_gold_ai_context(
            include_chart=False,
            client=cli,
            setup_override=wide_zone_setup,
            bars_override={"H1": [], "M15": [], "M5": bars_5m},
        )
        cands = ctx["structure_map"]["limit_entry_candidates"]
        buy_cand = cands["buy_limit_zone"]
        assert buy_cand is not None
        assert buy_cand["sl_distance_usd"] <= 8.00
        assert buy_cand["rr_ratio"] >= 1.50
        # Wide $13.07 zone clamped fibo_650 (3543.40) down >$2.50 to 3537.85 -> flagged clamped_to_sl_cap & deferred to micro_limit
        assert buy_cand["clamped_to_sl_cap"] is True
        assert buy_cand["passes_hard_gate"] is False
        assert cands["last_closed_m5_retrace_50"] is not None

        # Place AI Buy Limit at candidate entry
        lim_res = ai_place_limit(
            direction="BUY",
            price=buy_cand["entry"],
            sl=buy_cand["sl"],
            tp=buy_cand["tp"],
            client=cli,
            current_price_override=3550.00,
            spread_override=0.22,
            save_chart=False,
        )
        assert lim_res["success"] is True
        tkt = lim_res["order"]["ticket"]

        # Price drops within 0.35x ATR ($3.71) of the Pending Limit -> wakes AI with LIMIT_APPROACHING!
        approaching_setup = dict(wide_zone_setup, current_price=round(buy_cand["entry"] + 2.80, 2))
        captured_kwargs = {}

        def spy_ctx(**kwargs):
            captured_kwargs.update(kwargs)
            return {"spy": True}

        wake_app = wait_for_trigger(
            poll_sec=20.0,
            max_wait_sec=900.0,
            limit_approach_atr=0.35,
            log_progress=False,
            client=cli,
            setup_fn=lambda: approaching_setup,
            context_fn=spy_ctx,
        )
        assert wake_app["wakeup_reason"] == "LIMIT_APPROACHING"
        assert captured_kwargs.get("include_chart") is True
        assert captured_kwargs.get("planned_trade", {}).get("entry") == buy_cand["entry"]

        # Once AI verifies & passes guard_ticket=tkt, radar does NOT re-wake on LIMIT_APPROACHING
        wake_guarded = wait_for_trigger(
            poll_sec=0.05,
            max_wait_sec=0.06,
            limit_approach_atr=0.35,
            guard_ticket=tkt,
            log_progress=False,
            client=cli,
            setup_fn=lambda: approaching_setup,
            context_fn=spy_ctx,
        )
        assert wake_guarded["wakeup_reason"] == "HEARTBEAT_TIMEOUT"

        # Verify exact next M5 close calculation
        dt_sample = datetime(2026, 11, 25, 4, 12, 30, tzinfo=timezone.utc)  # 2m30s elapsed in 5m bar
        assert _seconds_to_next_m5_close(dt_sample, buffer_sec=3.0) == 153.0


def test_wide_zone_micro_limit_approach_momentum_and_direct_m5_knife_guard():
    from src.execution.ai_trader_bridge import protect_ai_pending_limits

    cli = MT5Client()
    cli.is_connected = False
    cli.account_info = {"login": 160219615, "currency": "USC"}

    # Real scenario: Wide $30.33 H1 Demand zone ($3502.97 - $3533.30), price stabilized at $3524.00 after $3515.84 M5 low
    t0 = datetime(2026, 11, 25, 6, 0, tzinfo=timezone.utc)
    bars_5m = []
    sample_ohlc = [
        (3523.38, 3523.58, 3515.84, 3521.20),  # Sweep & bounce wick at 3515.84
        (3521.26, 3523.35, 3516.75, 3521.44),
        (3521.44, 3525.10, 3520.80, 3523.90),
        (3523.90, 3524.60, 3522.90, 3524.00),  # Calm consolidation
    ]
    for idx, (o, h, l, c) in enumerate(sample_ohlc):
        bars_5m.append(
            Bar(
                symbol="XAUUSDc",
                timeframe=TimeFrame.M5,
                open_time=t0 + timedelta(minutes=idx * 5),
                close_time=t0 + timedelta(minutes=(idx + 1) * 5),
                open=o,
                high=h,
                low=l,
                close=c,
                volume=150.0,
                is_confirmed=(idx < 3),
                status=DataStatus.SIMULATION,
                session=SessionType.REGULAR,
            )
        )

    h1_wide_setup = {
        "mt5_symbol": "XAUUSDc",
        "current_price": 3524.00,
        "current_atr": 10.11,
        "live_bar_range": 1.70,
        "spread": 0.22,
        "status": "REJECTED_SL_TOO_WIDE",
        "demand_zones": [{
            "type": "DEMAND",
            "pattern": "RBR",
            "timeframe": "1H",
            "zone_low": 3502.97,
            "zone_high": 3533.30,
            "zone_mid": 3518.14,
        }],
        "supply_zones": [{
            "type": "SUPPLY",
            "pattern": "RBD",
            "timeframe": "15m & 1H",
            "zone_low": 3557.12,
            "zone_high": 3577.34,
            "zone_mid": 3567.23,
        }],
        "nearest_demand": {
            "type": "DEMAND",
            "pattern": "RBR",
            "timeframe": "1H",
            "zone_low": 3502.97,
            "zone_high": 3533.30,
            "zone_mid": 3518.14,
        },
        "nearest_supply": {
            "type": "SUPPLY",
            "pattern": "RBD",
            "timeframe": "15m & 1H",
            "zone_low": 3557.12,
            "zone_high": 3577.34,
            "zone_mid": 3567.23,
        },
    }

    p_news, p_roll = _peaceful_bridge_guards()
    with p_news, p_roll:
        ctx = build_gold_ai_context(
            include_chart=False,
            client=cli,
            setup_override=h1_wide_setup,
            bars_override={"H1": [], "M15": [], "M5": bars_5m},
        )
        mom = ctx["structure_map"]["approach_momentum"]
        assert mom["buy_side_status"] == "SAFE_TO_LIMIT"

        micro = ctx["structure_map"]["limit_entry_candidates"]["micro_buy_limit"]
        assert micro is not None
        assert micro["anchor_m5_low"] == 3515.84
        assert micro["entry"] < 3524.00
        assert micro["sl"] < 3515.84
        assert micro["sl_distance_usd"] <= 8.00
        assert micro["rr_ratio"] >= 1.50
        assert micro["passes_hard_gate"] is True

        # Place the micro buy limit and verify Hard Risk Gate accepts it
        lim_res = ai_place_limit(
            direction="BUY",
            price=micro["entry"],
            sl=micro["sl"],
            tp=micro["tp"],
            client=cli,
            current_price_override=3524.00,
            spread_override=0.22,
            save_chart=False,
        )
        assert lim_res["success"] is True

        # Now simulate a sudden violent M5 bearish marubozu slamming toward the pending limit (even if status != REJECTED_FALLING_KNIFE)
        violent_bar = Bar(
            symbol="XAUUSDc",
            timeframe=TimeFrame.M5,
            open_time=t0 + timedelta(minutes=20),
            close_time=t0 + timedelta(minutes=25),
            open=3533.00,
            high=3533.20,
            low=3521.00,   # $12.20 range (~2.0x M5_ATR)
            close=3521.40, # $11.60 bearish body (~95% marubozu)
            volume=500.0,
            is_confirmed=False,
            status=DataStatus.SIMULATION,
            session=SessionType.REGULAR,
        )
        ctx_fast = build_gold_ai_context(
            include_chart=False,
            client=cli,
            setup_override=dict(h1_wide_setup, current_price=3521.40),
            bars_override={"H1": [], "M15": [], "M5": bars_5m[:-1] + [violent_bar]},
        )
        assert ctx_fast["structure_map"]["approach_momentum"]["buy_side_status"] == "FAST_IMPULSE_WAIT"

        # Watchdog cancels the pending limit immediately on direct M5 violent impulse near limit
        guard_res = protect_ai_pending_limits(
            dict(h1_wide_setup, current_price=3521.40, status="WAITING_FOR_REJECTION"),
            cli,
            bars_5m_override=[violent_bar],
        )
        assert len(guard_res["cancelled"]) == 1
        assert len(cli.get_pending_orders()) == 0


def test_smart_radar_missed_tp_cancel_opposite_zone_m5_subzone_and_displacement():
    cli = MT5Client()
    cli.is_connected = False
    cli.account_info = {"login": 160219615, "currency": "USC"}

    wide_range_setup = {
        "mt5_symbol": "XAUUSDc",
        "current_price": 3518.00,
        "current_atr": 10.00,
        "live_bar_range": 2.00,
        "spread": 0.22,
        "status": "WAITING_FOR_ZONE",
        "demand_zones": [{
            "type": "DEMAND",
            "pattern": "M15_SUPPORT",
            "timeframe": "15m",
            "zone_low": 3482.00,
            "zone_high": 3486.50,
            "zone_mid": 3484.25,
        }],
        "supply_zones": [{
            "type": "SUPPLY",
            "pattern": "M15_RESISTANCE",
            "timeframe": "15m",
            "zone_low": 3535.50,
            "zone_high": 3542.50,
            "zone_mid": 3539.00,
        }],
        "nearest_demand": {
            "type": "DEMAND",
            "pattern": "M15_SUPPORT",
            "timeframe": "15m",
            "zone_low": 3482.00,
            "zone_high": 3486.50,
            "zone_mid": 3484.25,
        },
        "nearest_supply": {
            "type": "SUPPLY",
            "pattern": "M15_RESISTANCE",
            "timeframe": "15m",
            "zone_low": 3535.50,
            "zone_high": 3542.50,
            "zone_mid": 3539.00,
        },
    }

    p_news, p_roll = _peaceful_bridge_guards()
    with p_news, p_roll:
        # 1. Pending SELL_LIMIT @ 3535.50 (TP 3520.50) auto-cancels & wakes immediately when price <= 3520.50
        cli.send_limit_order("XAUUSDc", "SELL", 0.06, 3535.50, 3543.00, 3520.50)
        res_tp_miss = wait_for_trigger(
            poll_sec=20.0,
            max_wait_sec=900.0,
            log_progress=False,
            client=cli,
            setup_fn=lambda: dict(wide_range_setup, current_price=3519.80),
            context_fn=lambda **kw: {"chart": kw.get("include_chart")},
        )
        assert res_tp_miss["wakeup_reason"] == "LIMIT_EMERGENCY_CANCELLED"
        assert "TP" in res_tp_miss["wakeup_detail"]
        assert len(cli.get_pending_orders()) == 0

        # 2. Opposite-side ZONE_PROXIMITY wakes even while holding a SELL_LIMIT within 2.0x ATR drift (above TP)
        cli.send_limit_order("XAUUSDc", "SELL", 0.06, 3525.00, 3532.50, 3500.00)
        opp_zone_setup = dict(
            wide_range_setup,
            current_price=3510.00,  # $15 drift <= 2.0x ATR ($20), above TP $3500, and within 0.7x ATR of Demand $3508
            nearest_demand={
                "type": "DEMAND",
                "pattern": "M15_SUPPORT",
                "timeframe": "15m",
                "zone_low": 3504.00,
                "zone_high": 3508.00,
                "zone_mid": 3506.00,
            },
        )
        res_opp = wait_for_trigger(
            poll_sec=20.0,
            max_wait_sec=900.0,
            proximity_atr=0.70,
            log_progress=False,
            client=cli,
            setup_fn=lambda: opp_zone_setup,
            context_fn=lambda **kw: {"chart": kw.get("include_chart")},
        )
        assert res_opp["wakeup_reason"] == "ZONE_PROXIMITY"
        assert "Demand" in res_opp["wakeup_detail"]
        cli.simulated_orders.clear()

        # 3. Fresh M5 Supply RBD inside wide $49 M15 range triggers M5_ZONE_PROXIMITY & produces m5_sell_limit_zone
        t0 = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
        m5_bars: list[Bar] = []
        for i in range(16):
            o = 3518.0 + (0.4 if i % 2 == 0 else -0.4)
            c = o + (0.5 if i % 2 == 0 else -0.5)
            m5_bars.append(
                Bar(
                    symbol="XAUUSDc",
                    timeframe=TimeFrame.M5,
                    open_time=t0 + timedelta(minutes=i * 5),
                    close_time=t0 + timedelta(minutes=(i + 1) * 5),
                    open=o,
                    high=max(o, c) + 0.4,
                    low=min(o, c) - 0.4,
                    close=c,
                    volume=100.0,
                    is_confirmed=True,
                    status=DataStatus.SIMULATION,
                    session=SessionType.REGULAR,
                )
            )
        # Leg1 up -> Tight Base @ 3522.0-3523.2 -> Strong Bearish Impulse to 3514.5 -> Live retest near 3520.2
        pattern_ohlc = [
            (3518.50, 3522.40, 3518.30, 3522.10, True),   # Leg 1 rally
            (3522.10, 3523.20, 3521.80, 3522.30, True),   # Tight base
            (3522.30, 3522.50, 3514.20, 3514.60, True),   # Strong bearish RBD impulse
            (3514.60, 3520.40, 3514.50, 3520.20, False),  # Live pullback approaching M5 Supply 3521.80-3523.20
        ]
        for idx, (o, h, l, c, conf) in enumerate(pattern_ohlc, start=16):
            m5_bars.append(
                Bar(
                    symbol="XAUUSDc",
                    timeframe=TimeFrame.M5,
                    open_time=t0 + timedelta(minutes=idx * 5),
                    close_time=t0 + timedelta(minutes=(idx + 1) * 5),
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=180.0,
                    is_confirmed=conf,
                    status=DataStatus.SIMULATION,
                    session=SessionType.REGULAR,
                )
            )

        mid_setup = dict(wide_range_setup, current_price=3520.20)
        ctx_m5 = build_gold_ai_context(
            include_chart=False,
            client=cli,
            setup_override=mid_setup,
            bars_override={"H1": [], "M15": [], "M5": m5_bars},
        )
        m5_sell = ctx_m5["structure_map"]["limit_entry_candidates"]["m5_sell_limit_zone"]
        assert m5_sell is not None
        assert m5_sell["sl_distance_usd"] <= 8.00
        assert m5_sell["rr_ratio"] >= 1.50
        assert m5_sell["passes_hard_gate"] is True

        res_m5_wake = wait_for_trigger(
            poll_sec=20.0,
            max_wait_sec=900.0,
            proximity_atr=0.70,
            log_progress=False,
            client=cli,
            setup_fn=lambda: mid_setup,
            bars_5m_fn=lambda _sym: m5_bars,
            context_fn=lambda **kw: {"chart": kw.get("include_chart")},
        )
        assert res_m5_wake["wakeup_reason"] == "M5_ZONE_PROXIMITY"
        assert res_m5_wake["context"]["chart"] is True

        # 4. Flat Price Displacement (>= 1.0x ATR from start_price) does NOT wake at iter 0, wakes on move
        seq_prices = iter([3512.00, 3516.00, 3501.50])  # drops $10.50 >= 1.0x ATR ($10.0) on 3rd poll
        res_disp = wait_for_trigger(
            poll_sec=0.01,
            max_wait_sec=10.0,
            proximity_atr=0.70,
            displacement_atr=1.0,
            log_progress=False,
            client=cli,
            setup_fn=lambda: dict(wide_range_setup, current_price=next(seq_prices)),
            context_fn=lambda **kw: {"chart": kw.get("include_chart")},
            sleep_fn=lambda _s: None,
        )
        assert res_disp["wakeup_reason"] == "MARKET_MOMENTUM_ALERT"
        assert res_disp["context"]["chart"] is False  # Gradual drift saves chart tokens

        # 5. Sudden M5 Volatility Spike when flat wakes with chart=True
        seq_rng = iter([(3512.00, 2.00), (3516.50, 10.50)])  # 10.50 >= 0.95 * 10.0
        res_spike = wait_for_trigger(
            poll_sec=0.01,
            max_wait_sec=10.0,
            proximity_atr=0.70,
            displacement_atr=1.0,
            log_progress=False,
            client=cli,
            setup_fn=lambda: (lambda px, rng: dict(wide_range_setup, current_price=px, live_bar_range=rng))(*next(seq_rng)),
            context_fn=lambda **kw: {"chart": kw.get("include_chart")},
            sleep_fn=lambda _s: None,
        )
        assert res_spike["wakeup_reason"] == "MARKET_MOMENTUM_ALERT"
        assert res_spike["context"]["chart"] is True


def test_limit_candidates_golden_zone_confluence_uses_fibo_or_fallback_618():
    cli = MT5Client()
    cli.is_connected = False
    cli.account_info = {"login": 160219615, "currency": "USC"}

    # fibo_650 (3562.0) is outside overlap [3563.0..3566.0], while fibo_618 (3564.20) is inside overlap
    setup = {
        "mt5_symbol": "XAUUSDc",
        "current_price": 3569.00,
        "current_atr": 5.00,
        "spread": 0.20,
        "live_bar_range": 1.20,
        "demand_zones": [{
            "type": "DEMAND",
            "pattern": "RBR",
            "timeframe": "15m",
            "label": "Demand 15m (RBR)",
            "zone_high": 3566.50,
            "zone_low": 3563.00,
            "zone_mid": 3564.75,
            "fibo_confluence": {
                "has_confluence": True,
                "fibo_650": 3562.00,
                "overlap_low": 3563.00,
                "overlap_high": 3566.00,
                "overlap_mid": 3564.50,
                "double_confluence": False,
            },
        }],
        "supply_zones": [{
            "type": "SUPPLY",
            "pattern": "DBD",
            "timeframe": "15m",
            "label": "Supply 15m (DBD)",
            "zone_high": 3585.00,
            "zone_low": 3582.00,
            "zone_mid": 3583.50,
        }],
        "fibo_buy": {"fibo_618": 3564.20, "fibo_650": 3562.00, "golden_zone_high": 3566.00, "golden_zone_low": 3560.00},
        "fibo_sell": {"fibo_618": 3580.00, "fibo_650": 3581.00, "golden_zone_high": 3581.50, "golden_zone_low": 3579.00},
    }
    setup["nearest_demand"] = setup["demand_zones"][0]
    setup["nearest_supply"] = setup["supply_zones"][0]

    ctx = build_gold_ai_context(
        include_chart=False,
        client=cli,
        setup_override=setup,
        bars_override={"H1": [], "M15": [], "M5": _make_sample_bars(TimeFrame.M5, count=12, start_price=3568.0)},
    )
    buy_cand = ctx["structure_map"]["limit_entry_candidates"]["buy_limit_zone"]
    assert buy_cand["entry_tier"] == "GOLDEN_ZONE_CONFLUENCE"
    assert buy_cand["confirmation_policy"] == "IMMEDIATE_LIMIT_RELAXED"
    assert buy_cand["shifted_from_nearest"] is False
    assert buy_cand["entry"] == 3564.20  # Falls back cleanly from out-of-overlap fibo_650 to fibo_618
    assert buy_cand["passes_hard_gate"] is True


def test_limit_candidates_shifts_to_nearby_golden_zone_when_nearest_has_no_overlap():
    cli = MT5Client()
    cli.is_connected = False
    cli.account_info = {"login": 160219615, "currency": "USC"}

    shallow_demand = {
        "type": "DEMAND",
        "pattern": "RBR",
        "timeframe": "15m",
        "label": "Shallow Demand",
        "zone_high": 3572.00,
        "zone_low": 3569.50,
        "zone_mid": 3570.75,
        "fibo_confluence": {"has_confluence": False},
    }
    nearby_golden_demand = {
        "type": "DEMAND",
        "pattern": "DBR",
        "timeframe": "15m",
        "label": "Golden Demand",
        "zone_high": 3566.50,
        "zone_low": 3563.00,
        "zone_mid": 3564.75,
        "fibo_confluence": {
            "has_confluence": True,
            "fibo_650": 3564.80,
            "overlap_low": 3563.50,
            "overlap_high": 3566.50,
            "overlap_mid": 3565.00,
            "double_confluence": True,
        },
    }
    setup = {
        "mt5_symbol": "XAUUSDc",
        "current_price": 3573.00,
        "current_atr": 6.00,  # max shift dist = 9.0 -> clamped to $10.0; 3573 - 3566.5 = $6.5 <= $10
        "spread": 0.20,
        "live_bar_range": 1.10,
        "demand_zones": [shallow_demand, nearby_golden_demand],
        "supply_zones": [{
            "type": "SUPPLY",
            "pattern": "DBD",
            "timeframe": "15m",
            "label": "Supply 15m",
            "zone_high": 3588.00,
            "zone_low": 3585.00,
            "zone_mid": 3586.50,
        }],
        "nearest_demand": shallow_demand,
        "fibo_buy": {"fibo_618": 3565.80, "fibo_650": 3564.80, "golden_zone_high": 3566.50, "golden_zone_low": 3562.00},
        "fibo_sell": {},
    }
    setup["nearest_supply"] = setup["supply_zones"][0]

    ctx = build_gold_ai_context(
        include_chart=False,
        client=cli,
        setup_override=setup,
        bars_override={"H1": [], "M15": [], "M5": _make_sample_bars(TimeFrame.M5, count=12, start_price=3572.0)},
    )
    buy_cand = ctx["structure_map"]["limit_entry_candidates"]["buy_limit_zone"]
    assert buy_cand["entry_tier"] == "NEARBY_GOLDEN_ZONE_SHIFT"
    assert buy_cand["shifted_from_nearest"] is True
    assert buy_cand["double_confluence"] is True
    assert buy_cand["zone_label"] == "Golden Demand"
    assert buy_cand["entry"] == 3564.80
    assert buy_cand["passes_hard_gate"] is True


def test_limit_candidates_blocks_shallow_no_fibo_and_allows_trend_pullback_or_h1_rr():
    cli = MT5Client()
    cli.is_connected = False
    cli.account_info = {"login": 160219615, "currency": "USC"}

    # 1. Shallow zone (3568-3572) way above Fibo 38.2% (3564.0) -> NO_FIBO_SUPPORT (passes_hard_gate = False)
    shallow_setup = {
        "mt5_symbol": "XAUUSDc",
        "current_price": 3574.00,
        "current_atr": 5.00,
        "spread": 0.20,
        "live_bar_range": 1.00,
        "demand_zones": [{
            "type": "DEMAND",
            "pattern": "RBR",
            "timeframe": "15m",
            "label": "Shallow Floating Demand",
            "zone_high": 3572.00,
            "zone_low": 3568.00,
            "zone_mid": 3570.00,
            "is_h1_role_reversal": False,
            "fibo_confluence": {"has_confluence": False, "has_ok_fibo": False, "fibo_tier": "NONE"},
        }],
        "supply_zones": [{
            "type": "SUPPLY",
            "pattern": "DBD",
            "timeframe": "15m",
            "label": "Supply 15m",
            "zone_high": 3588.00,
            "zone_low": 3585.00,
            "zone_mid": 3586.50,
        }],
        "fibo_buy": {
            "fibo_382": 3564.00,
            "fibo_500": 3561.00,
            "fibo_618": 3558.00,
            "fibo_650": 3556.00,
            "golden_zone_high": 3558.00,
            "golden_zone_low": 3554.00,
        },
        "fibo_sell": {},
    }
    shallow_setup["nearest_demand"] = shallow_setup["demand_zones"][0]
    shallow_setup["nearest_supply"] = shallow_setup["supply_zones"][0]

    ctx_blocked = build_gold_ai_context(
        include_chart=False,
        client=cli,
        setup_override=shallow_setup,
        bars_override={"H1": [], "M15": [], "M5": _make_sample_bars(TimeFrame.M5, count=12, start_price=3573.0)},
    )
    blocked_cand = ctx_blocked["structure_map"]["limit_entry_candidates"]["buy_limit_zone"]
    assert blocked_cand["entry_tier"] == "NO_FIBO_SUPPORT"
    assert blocked_cand["confirmation_policy"] == "BLOCKED_SHALLOW_NO_FIBO"
    assert blocked_cand["passes_hard_gate"] is False

    # 2. Zone overlapping Fibo 50.0% (3569.50 inside [3568.0..3572.0]) -> TREND_PULLBACK_FIBO (passes_hard_gate = True)
    pullback_setup = dict(shallow_setup)
    pullback_setup["fibo_buy"] = {
        "fibo_382": 3573.00,
        "fibo_500": 3569.50,
        "fibo_618": 3566.00,
        "fibo_650": 3565.00,
        "golden_zone_high": 3566.00,
        "golden_zone_low": 3562.00,
    }
    ctx_pb = build_gold_ai_context(
        include_chart=False,
        client=cli,
        setup_override=pullback_setup,
        bars_override={"H1": [], "M15": [], "M5": _make_sample_bars(TimeFrame.M5, count=12, start_price=3573.0)},
    )
    pb_cand = ctx_pb["structure_map"]["limit_entry_candidates"]["buy_limit_zone"]
    assert pb_cand["entry_tier"] == "TREND_PULLBACK_FIBO"
    assert pb_cand["has_ok_fibo"] is True
    assert pb_cand["entry"] == 3569.50
    assert pb_cand["sl_distance_usd"] <= 8.00
    assert pb_cand["passes_hard_gate"] is True

    # 3. Counter-trend H1+M15 BEARISH blocks blind BUY limit even with Fibo confluence
    ct_setup = dict(pullback_setup, trend_indicators={"trend": "BEARISH", "h1_trend": "BEARISH"})
    ctx_ct = build_gold_ai_context(
        include_chart=False,
        client=cli,
        setup_override=ct_setup,
        bars_override={"H1": [], "M15": [], "M5": _make_sample_bars(TimeFrame.M5, count=12, start_price=3573.0)},
    )
    ct_cand = ctx_ct["structure_map"]["limit_entry_candidates"]["buy_limit_zone"]
    assert ct_cand["passes_hard_gate"] is False
    assert ct_cand["confirmation_policy"] == "BLOCKED_COUNTER_TREND_BLIND_LIMIT"

    # 4. M15 CHoCH Bearish blocks blind BUY limit even when EMA trend is still BULLISH/NEUTRAL
    choch_setup = dict(
        pullback_setup,
        trend_indicators={
            "trend": "BULLISH",
            "h1_trend": "BULLISH",
            "m15_structure": {"bias": "BEARISH", "pattern": "HH/HL", "live_break": "CHOCH_BEAR", "last_sh": 3582.0, "last_sl": 3571.0},
            "h1_structure": {"bias": "BULLISH", "pattern": "HH/HL", "live_break": "NONE", "last_sh": 3590.0, "last_sl": 3550.0},
        },
    )
    ctx_choch = build_gold_ai_context(
        include_chart=False,
        client=cli,
        setup_override=choch_setup,
        bars_override={"H1": [], "M15": [], "M5": _make_sample_bars(TimeFrame.M5, count=12, start_price=3573.0)},
    )
    choch_cand = ctx_choch["structure_map"]["limit_entry_candidates"]["buy_limit_zone"]
    assert choch_cand["passes_hard_gate"] is False
    assert choch_cand["confirmation_policy"] == "BLOCKED_M15_CHOCH_COUNTER_TREND"
    assert ctx_choch["session_and_trend"]["trend_indicators"]["m15_structure"]["live_break"] == "CHOCH_BEAR"
