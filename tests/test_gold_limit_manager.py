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
