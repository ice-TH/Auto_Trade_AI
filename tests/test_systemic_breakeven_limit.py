import pytest
from src.execution.mt5_client import MT5Client

def test_breakeven_lock_buy():
    client = MT5Client()
    client.simulated_positions = [{
        "ticket": 99901,
        "symbol": "XAUUSDc",
        "direction": "BUY",
        "volume": 0.06,
        "open_price": 3620.00,
        "current_price": 3627.00,  # Gain = +$7.00
        "sl": 3614.00,             # Initial Risk = $6.00 -> 7.00/6.00 = 1.16x R >= 1.0x R
        "tp": 3635.00,
        "profit_usd": 0.42,
        "profit_thb": 14.70,
        "time": "2026-11-24 12:00:00",
        "comment": "Test Buy"
    }]
    
    # Run Breakeven check
    locks = client.check_and_apply_breakeven_locks(min_r_multiple=1.0)
    assert len(locks) == 1
    lock = locks[0]
    assert lock["ticket"] == 99901
    assert lock["status"] == "LOCKED"
    assert lock["new_sl"] >= 3620.00  # Must be locked at or above open price
    assert client.simulated_positions[0]["sl"] == lock["new_sl"]

def test_breakeven_not_triggered_when_under_1r():
    client = MT5Client()
    client.simulated_positions = [{
        "ticket": 99902,
        "symbol": "XAUUSDc",
        "direction": "BUY",
        "volume": 0.06,
        "open_price": 3620.00,
        "current_price": 3623.00,  # Gain = +$3.00
        "sl": 3614.00,             # Initial Risk = $6.00 -> 3.00/6.00 = 0.5x R < 1.0x R
        "tp": 3635.00,
        "profit_usd": 0.18,
        "profit_thb": 6.30,
        "time": "2026-11-24 12:00:00",
        "comment": "Test Buy Sub 1R"
    }]
    
    locks = client.check_and_apply_breakeven_locks(min_r_multiple=1.0)
    assert len(locks) == 0
    assert client.simulated_positions[0]["sl"] == 3614.00  # SL untouched

def test_breakeven_lock_sell():
    client = MT5Client()
    client.simulated_positions = [{
        "ticket": 99903,
        "symbol": "XAUUSDc",
        "direction": "SELL",
        "volume": 0.06,
        "open_price": 3630.00,
        "current_price": 3624.00,  # Gain = +$6.00
        "sl": 3635.00,             # Initial Risk = $5.00 -> 6.00/5.00 = 1.20x R >= 1.0x R
        "tp": 3615.00,
        "profit_usd": 0.36,
        "profit_thb": 12.60,
        "time": "2026-11-24 12:00:00",
        "comment": "Test Sell"
    }]
    
    locks = client.check_and_apply_breakeven_locks(min_r_multiple=1.0)
    assert len(locks) == 1
    lock = locks[0]
    assert lock["ticket"] == 99903
    assert lock["status"] == "LOCKED"
    assert lock["new_sl"] <= 3630.00  # Must be locked at or below open price
    assert client.simulated_positions[0]["sl"] == lock["new_sl"]
