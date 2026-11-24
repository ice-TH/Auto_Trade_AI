from datetime import datetime, timezone
import pytest
from src.execution.mt5_client import MT5Client

def test_simulated_send_limit_order():
    client = MT5Client()
    client.is_connected = False  # Test Simulated Demo engine
    
    # 1. Reject without Hard SL
    res_no_sl = client.send_limit_order(
        symbol="XAUUSDm",
        direction="BUY",
        volume=0.01,
        price=3615.0,
        sl_price=0.0,
        tp_price=3625.0
    )
    assert res_no_sl["success"] is False
    assert "mandatory" in res_no_sl["error"]
    
    # 2. Accept valid limit order with 10m TTL
    res = client.send_limit_order(
        symbol="XAUUSDm",
        direction="BUY",
        volume=0.01,
        price=3615.0,
        sl_price=3612.0,
        tp_price=3625.0,
        expiry_minutes=10
    )
    assert res["success"] is True
    ticket = res["ticket"]
    assert ticket > 0
    
    orders = client.get_pending_orders("XAUUSDm")
    assert len(orders) >= 1
    found = next((o for o in orders if o["ticket"] == ticket), None)
    assert found is not None
    assert found["price"] == 3615.0
    
    # 3. Test Lease Renewal
    renew_res = client.renew_pending_order_expiry(ticket, additional_minutes=10)
    assert renew_res["success"] is True
    assert renew_res["renewal_count"] == 1
    
    # 4. Test Cancellation
    cancel_res = client.cancel_pending_order(ticket)
    assert cancel_res["success"] is True
    
    # Confirm it's gone
    orders_after = client.get_pending_orders("XAUUSDm")
    assert not any(o["ticket"] == ticket for o in orders_after)
