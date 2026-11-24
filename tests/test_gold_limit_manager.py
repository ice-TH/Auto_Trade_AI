from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from src.execution.mt5_client import MT5Client
from src.analysis.gold_limit_manager import (
    manage_gold_limits,
    _PENDING_ORDER_METADATA,
    MAX_RENEWALS_ALLOWED
)

def test_manage_gold_limits_places_discount_limit():
    client = MT5Client()
    client.is_connected = False
    _PENDING_ORDER_METADATA.clear()
    
    # Mock peaceful time (no news blackout) and normal spread
    with patch("src.analysis.gold_limit_manager.is_news_blackout", return_value=(False, "Normal")), \
         patch("src.analysis.gold_limit_manager.is_spread_acceptable", return_value=(True, "Normal")):
        
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
                "zone_mid": 3616.0  # Discount 50%
            }
        }
        
        res = manage_gold_limits(gold_setup, client=client)
        assert res["active_pending_count"] == 1
        assert any("PLACED BUY_LIMIT" in a for a in res["actions_taken"])
        
        # Verify order was placed at zone_mid 3616.0
        orders = client.get_pending_orders("XAUUSDm")
        assert orders[0]["price"] == 3616.0

def test_manage_gold_limits_cancels_during_news():
    client = MT5Client()
    client.is_connected = False
    _PENDING_ORDER_METADATA.clear()
    
    # First, place an order
    order_res = client.send_limit_order("XAUUSDm", "BUY", 0.01, 3616.0, 3612.0, 3625.0)
    ticket = order_res["ticket"]
    
    # Simulate News Blackout active
    with patch("src.analysis.gold_limit_manager.is_news_blackout", return_value=(True, "CPI Release")):
        gold_setup = {
            "symbol": "XAUUSDm",
            "current_price": 3618.0,
            "current_atr": 3.0,
            "status": "WAITING_FOR_REJECTION",
            "recommended_direction": "NEUTRAL",
            "spread": 0.20
        }
        res = manage_gold_limits(gold_setup, client=client)
        assert res["active_pending_count"] == 0
        assert any(f"CANCELLED #{ticket}" in a for a in res["actions_taken"])

def test_manage_gold_limits_max_renewals_cap():
    client = MT5Client()
    client.is_connected = False
    _PENDING_ORDER_METADATA.clear()
    
    order_res = client.send_limit_order("XAUUSDm", "BUY", 0.01, 3616.0, 3612.0, 3625.0)
    ticket = order_res["ticket"]
    
    # Pretend it has already been renewed 5 times
    _PENDING_ORDER_METADATA[ticket] = {
        "renewal_count": MAX_RENEWALS_ALLOWED,
        "created_at": datetime.now(timezone.utc)
    }
    
    with patch("src.analysis.gold_limit_manager.is_news_blackout", return_value=(False, "Normal")), \
         patch("src.analysis.gold_limit_manager.is_spread_acceptable", return_value=(True, "Normal")):
        
        gold_setup = {
            "symbol": "XAUUSDm",
            "current_price": 3617.0,
            "current_atr": 3.0,
            "status": "WAITING_FOR_REJECTION",
            "recommended_direction": "NEUTRAL",
            "spread": 0.20
        }
        res = manage_gold_limits(gold_setup, client=client)
        # Should cancel because max renewals reached
        assert res["active_pending_count"] == 0
        assert any(f"CANCELLED #{ticket}" in a and "ต่อเวลาสูงสุด" in a for a in res["actions_taken"])

def test_manage_gold_limits_cancels_on_falling_knife():
    client = MT5Client()
    client.is_connected = False
    _PENDING_ORDER_METADATA.clear()
    
    order_res = client.send_limit_order("XAUUSDm", "BUY", 0.01, 3616.0, 3612.0, 3625.0)
    ticket = order_res["ticket"]
    
    with patch("src.analysis.gold_limit_manager.is_news_blackout", return_value=(False, "Normal")), \
         patch("src.analysis.gold_limit_manager.is_spread_acceptable", return_value=(True, "Normal")):
        
        gold_setup = {
            "symbol": "XAUUSDm",
            "current_price": 3616.5,
            "current_atr": 3.0,
            "status": "REJECTED_FALLING_KNIFE",
            "recommended_direction": "NEUTRAL",
            "spread": 0.20
        }
        res = manage_gold_limits(gold_setup, client=client)
        assert res["active_pending_count"] == 0
        assert any("Falling Knife" in a for a in res["actions_taken"])

def test_manage_gold_limits_cancels_when_structure_broken():
    client = MT5Client()
    client.is_connected = False
    _PENDING_ORDER_METADATA.clear()
    
    # Placed BUY limit at 3616.0 with SL at 3612.0
    order_res = client.send_limit_order("XAUUSDm", "BUY", 0.01, 3616.0, 3612.0, 3625.0)
    ticket = order_res["ticket"]
    
    with patch("src.analysis.gold_limit_manager.is_news_blackout", return_value=(False, "Normal")), \
         patch("src.analysis.gold_limit_manager.is_spread_acceptable", return_value=(True, "Normal")):
        
        # Price collapsed to 3610.0 (below SL and broken demand)
        gold_setup = {
            "symbol": "XAUUSDm",
            "current_price": 3610.0,
            "current_atr": 3.0,
            "status": "WAITING_FOR_REJECTION",
            "recommended_direction": "NEUTRAL",
            "spread": 0.20,
            "nearest_demand": {
                "zone_high": 3618.0,
                "zone_low": 3614.0,
                "zone_mid": 3616.0
            }
        }
        res = manage_gold_limits(gold_setup, client=client)
        assert res["active_pending_count"] == 0
        assert any("โครงสร้าง Demand ถูกทำลาย" in a for a in res["actions_taken"])

def test_manage_gold_limits_places_actionable_limit_up_to_8_usd():
    client = MT5Client()
    client.is_connected = False
    _PENDING_ORDER_METADATA.clear()
    
    with patch("src.analysis.gold_limit_manager.is_news_blackout", return_value=(False, "Normal")), \
         patch("src.analysis.gold_limit_manager.is_spread_acceptable", return_value=(True, "Normal")):
        
        # Setup has SL distance of 7.50 USD (which is <= 8.00 USD cap)
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
            "nearest_demand": {
                "zone_high": 3622.0,
                "zone_low": 3614.0,
                "zone_mid": 3618.0
            }
        }
        res = manage_gold_limits(gold_setup, client=client)
        assert res["active_pending_count"] == 1
        assert any("PLACED BUY_LIMIT" in a and "3620.00" in a for a in res["actions_taken"])

