import pytest
from src.execution.mt5_client import MT5Client
from src.execution.reconciliation import OrderReconciler

def test_mt5_client_mandatory_hard_sl():
    client = MT5Client()
    # Sending order with sl_price <= 0 must fail
    res_no_sl = client.send_order(
        symbol="NVDA", direction="BUY", volume=0.01, sl_price=0.0, tp_price=160.0
    )
    assert res_no_sl["success"] is False
    assert "Hard Stop Loss is mandatory" in res_no_sl["error"]

def test_mt5_client_order_send_and_close():
    client = MT5Client()
    # Execute simulated demo order with valid SL
    res = client.send_order(
        symbol="AAPL", direction="BUY", volume=0.01, sl_price=220.0, tp_price=240.0
    )
    assert res["success"] is True
    ticket = res["ticket"]
    assert ticket > 0

    # Verify position is recorded
    positions = client.get_open_positions()
    assert any(p["ticket"] == ticket for p in positions)

    # Close position
    close_res = client.close_position(ticket)
    assert close_res["success"] is True

    # Verify position was removed
    positions_after = client.get_open_positions()
    assert not any(p["ticket"] == ticket for p in positions_after)

def test_mt5_emergency_close_all():
    client = MT5Client()
    # Open 2 demo positions
    client.send_order("NVDA", "BUY", 0.01, sl_price=140.0, tp_price=160.0)
    client.send_order("MSFT", "BUY", 0.01, sl_price=410.0, tp_price=440.0)
    assert len(client.get_open_positions()) >= 2

    em_res = client.emergency_close_all()
    assert em_res["status"] == "EMERGENCY_CLOSE_COMPLETED"
    assert em_res["closed_count"] >= 2
    assert len(client.get_open_positions()) == 0

def test_order_reconciler_idempotency():
    reconciler = OrderReconciler()
    sym = "GOOGL"
    tf = "1D"
    bar_time = "2026-11-21_19"
    direction = "BUY"

    # Initially not duplicate
    assert reconciler.is_order_duplicate(sym, tf, bar_time, direction) is False

    # Record execution
    reconciler.record_order_execution(sym, tf, bar_time, direction)

    # Now duplicate check must return True
    assert reconciler.is_order_duplicate(sym, tf, bar_time, direction) is True
