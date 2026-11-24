from datetime import datetime, timezone
from unittest.mock import patch
from src.execution.mt5_client import MT5Client
from src.analysis.gold_limit_manager import (
    manage_gold_limits,
    _PENDING_ORDER_METADATA,
    MAX_RENEWALS_ALLOWED,
)
from src.analysis.gold_position_manager import manage_gold_positions


def _peaceful_guards():
    return (
        patch("src.analysis.gold_limit_manager.is_news_blackout", return_value=(False, "Normal")),
        patch("src.analysis.gold_limit_manager.is_rollover_blackout", return_value=(False, "Normal")),
        patch("src.analysis.gold_limit_manager.is_spread_acceptable", return_value=(True, "Normal")),
    )


def test_manage_gold_limits_places_discount_limit():
    client = MT5Client()
    client.is_connected = False
    _PENDING_ORDER_METADATA.clear()

    p1, p2, p3 = _peaceful_guards()
    with p1, p2, p3:
        gold_setup = {
            "symbol": "XAUUSDm",
            "current_price": 3618.0,
            "current_atr": 3.0,
            "status": "WAITING_FOR_REJECTION",
            "recommended_direction": "NEUTRAL",
            "spread": 0.20,
            "nearest_demand": {
                "zone_high": 3618.0,
                "zone_low": 3614.0,
                "zone_mid": 3616.0,
            },
        }

        res = manage_gold_limits(gold_setup, client=client)
        assert res["active_pending_count"] == 1
        assert any("PLACED BUY_LIMIT" in a for a in res["actions_taken"])

        orders = client.get_pending_orders("XAUUSDm")
        assert orders[0]["price"] == 3616.0
        # Structural SL: 3614.0 - (3.0 * 0.75) = 3611.75
        assert orders[0]["sl"] == 3611.75


def test_manage_gold_limits_single_position_guard_blocks_and_cancels():
    """When an XAU position is already open, pending limits must be cancelled and no new limits placed."""
    client = MT5Client()
    client.is_connected = False
    _PENDING_ORDER_METADATA.clear()

    # Existing pending order
    order_res = client.send_limit_order("XAUUSDm", "BUY", 0.01, 3616.0, 3612.0, 3625.0)
    ticket = order_res["ticket"]

    # Simulate an active open Gold position
    client.simulated_positions = [{
        "ticket": 88801,
        "symbol": "XAUUSDm",
        "direction": "BUY",
        "volume": 0.01,
        "open_price": 3617.0,
        "current_price": 3619.0,
        "sl": 3612.0,
        "tp": 3628.0,
    }]

    p1, p2, p3 = _peaceful_guards()
    with p1, p2, p3:
        gold_setup = {
            "symbol": "XAUUSDm",
            "current_price": 3619.0,
            "current_atr": 3.0,
            "status": "ACTIONABLE_BUY_LIMIT",
            "recommended_direction": "BUY",
            "recommended_entry": 3616.0,
            "recommended_sl": 3611.75,
            "recommended_tp": 3626.0,
            "spread": 0.20,
            "nearest_demand": {"zone_high": 3618.0, "zone_low": 3614.0, "zone_mid": 3616.0},
        }
        res = manage_gold_limits(gold_setup, client=client)
        assert res["has_open_position"] is True
        assert res["active_pending_count"] == 0
        assert any(f"CANCELLED #{ticket}" in a and "Single-Position Guard" in a for a in res["actions_taken"])
        assert not any("PLACED" in a for a in res["actions_taken"])


def test_manage_gold_limits_never_places_buy_and_sell_simultaneously():
    """Mutual exclusion: Even if both demand and supply exist in WAITING_FOR_REJECTION, at most ONE order is placed."""
    client = MT5Client()
    client.is_connected = False
    _PENDING_ORDER_METADATA.clear()

    p1, p2, p3 = _peaceful_guards()
    with p1, p2, p3:
        gold_setup = {
            "symbol": "XAUUSDm",
            "current_price": 3618.5,
            "current_atr": 3.0,
            "status": "WAITING_FOR_REJECTION",
            "recommended_direction": "NEUTRAL",
            "spread": 0.20,
            "nearest_demand": {"zone_high": 3618.0, "zone_low": 3615.0, "zone_mid": 3616.5},
            "nearest_supply": {"zone_high": 3628.0, "zone_low": 3625.0, "zone_mid": 3626.5},
        }
        res = manage_gold_limits(gold_setup, client=client)
        assert res["active_pending_count"] == 1
        placed_actions = [a for a in res["actions_taken"] if "PLACED" in a]
        assert len(placed_actions) == 1


def test_manage_gold_limits_cancels_during_news_or_volatility_spike():
    client = MT5Client()
    client.is_connected = False
    _PENDING_ORDER_METADATA.clear()

    order_res = client.send_limit_order("XAUUSDm", "BUY", 0.01, 3616.0, 3612.0, 3625.0)
    ticket = order_res["ticket"]

    with patch("src.analysis.gold_limit_manager.is_news_blackout", return_value=(True, "CPI Release")), \
         patch("src.analysis.gold_limit_manager.is_rollover_blackout", return_value=(False, "Normal")):
        gold_setup = {
            "symbol": "XAUUSDm",
            "current_price": 3618.0,
            "current_atr": 3.0,
            "status": "WAITING_FOR_REJECTION",
            "recommended_direction": "NEUTRAL",
            "spread": 0.20,
        }
        res = manage_gold_limits(gold_setup, client=client)
        assert res["active_pending_count"] == 0
        assert any(f"CANCELLED #{ticket}" in a for a in res["actions_taken"])

    # Volatility Spike test
    order2 = client.send_limit_order("XAUUSDm", "BUY", 0.01, 3616.0, 3612.0, 3625.0)
    t2 = order2["ticket"]
    p1, p2, p3 = _peaceful_guards()
    with p1, p2, p3:
        spike_setup = {
            "symbol": "XAUUSDm",
            "current_price": 3618.0,
            "current_atr": 3.0,
            "live_bar_range": 9.5,  # > 2.2x ATR -> Volatility Spike!
            "status": "WAITING_FOR_REJECTION",
            "recommended_direction": "NEUTRAL",
            "spread": 0.20,
        }
        res2 = manage_gold_limits(spike_setup, client=client)
        assert res2["volatility_spike"] is True
        assert res2["active_pending_count"] == 0
        assert any(f"CANCELLED #{t2}" in a for a in res2["actions_taken"])


def test_manage_gold_limits_max_renewals_cap():
    client = MT5Client()
    client.is_connected = False
    _PENDING_ORDER_METADATA.clear()

    order_res = client.send_limit_order("XAUUSDm", "BUY", 0.01, 3616.0, 3612.0, 3625.0)
    ticket = order_res["ticket"]

    _PENDING_ORDER_METADATA[ticket] = {
        "renewal_count": MAX_RENEWALS_ALLOWED,
        "created_at": datetime.now(timezone.utc),
    }

    p1, p2, p3 = _peaceful_guards()
    with p1, p2, p3:
        gold_setup = {
            "symbol": "XAUUSDm",
            "current_price": 3617.0,
            "current_atr": 3.0,
            "status": "WAITING_FOR_REJECTION",
            "recommended_direction": "NEUTRAL",
            "spread": 0.20,
        }
        res = manage_gold_limits(gold_setup, client=client)
        assert res["active_pending_count"] == 0
        assert any(f"CANCELLED #{ticket}" in a and "ต่อเวลาสูงสุด" in a for a in res["actions_taken"])


def test_manage_gold_limits_cancels_on_falling_knife_and_structure_break():
    client = MT5Client()
    client.is_connected = False
    _PENDING_ORDER_METADATA.clear()

    order_res = client.send_limit_order("XAUUSDm", "BUY", 0.01, 3616.0, 3612.0, 3625.0)
    ticket = order_res["ticket"]

    p1, p2, p3 = _peaceful_guards()
    with p1, p2, p3:
        gold_setup = {
            "symbol": "XAUUSDm",
            "current_price": 3616.5,
            "current_atr": 3.0,
            "status": "REJECTED_FALLING_KNIFE",
            "recommended_direction": "NEUTRAL",
            "spread": 0.20,
        }
        res = manage_gold_limits(gold_setup, client=client)
        assert res["active_pending_count"] == 0
        assert any("Falling Knife" in a for a in res["actions_taken"])

    # Structure break
    order2 = client.send_limit_order("XAUUSDm", "BUY", 0.01, 3616.0, 3612.0, 3625.0)
    with p1, p2, p3:
        broken_setup = {
            "symbol": "XAUUSDm",
            "current_price": 3610.0,
            "current_atr": 3.0,
            "status": "WAITING_FOR_REJECTION",
            "recommended_direction": "NEUTRAL",
            "spread": 0.20,
            "nearest_demand": {"zone_high": 3618.0, "zone_low": 3614.0, "zone_mid": 3616.0},
        }
        res2 = manage_gold_limits(broken_setup, client=client)
        assert res2["active_pending_count"] == 0
        assert any("โครงสร้าง Demand ถูกทำลาย" in a for a in res2["actions_taken"])


def test_manage_gold_limits_places_actionable_limit_up_to_8_usd():
    client = MT5Client()
    client.is_connected = False
    _PENDING_ORDER_METADATA.clear()

    p1, p2, p3 = _peaceful_guards()
    with p1, p2, p3:
        gold_setup = {
            "symbol": "XAUUSDm",
            "current_price": 3625.0,
            "current_atr": 4.0,
            "status": "ACTIONABLE_BUY_LIMIT",
            "execution_mode": "LIMIT",
            "recommended_direction": "BUY",
            "recommended_entry": 3620.0,
            "recommended_sl": 3612.5,  # 7.5 USD risk <= 8.0 USD cap
            "recommended_tp": 3635.0,  # 15.0 USD reward -> R:R 2.0
            "spread": 0.20,
            "nearest_demand": {"zone_high": 3622.0, "zone_low": 3614.0, "zone_mid": 3618.0},
        }
        res = manage_gold_limits(gold_setup, client=client)
        assert res["active_pending_count"] == 1
        assert any("PLACED BUY_LIMIT" in a and "3620.00" in a for a in res["actions_taken"])


def test_unified_gold_position_manager_locks_at_1r():
    """Verify gold_position_manager locks BE at +1.0R (e.g., +$5.50 gain on $5.00 risk) without waiting for $9.00."""
    client = MT5Client()
    client.is_connected = False
    client.simulated_positions = [{
        "ticket": 77701,
        "symbol": "XAUUSDc",
        "direction": "BUY",
        "volume": 0.06,
        "open_price": 3620.00,
        "current_price": 3625.50,  # +$5.50 gain (< old $9.00 threshold, but 1.10R >= 1.0R!)
        "sl": 3615.00,             # $5.00 initial risk
        "tp": 3632.00,
    }]

    res = manage_gold_positions(client=client, min_r_multiple=1.0)
    assert res["status"] == "COMPLETED"
    assert len(res["actions_taken"]) == 1
    assert "Auto Break-Even" in res["actions_taken"][0]
    assert client.simulated_positions[0]["sl"] > 3620.00
