import pytest
from src.risk.sizing import calculate_position_size
from src.risk.limits import check_portfolio_risk_limits

def test_position_size_valid():
    # Capital 3,000 THB, USD/THB = 35.0 -> Capital USD = ~$85.71
    # Max Notional USD = $85.71 * 5 = $428.57 = 15,000 THB
    # Stock price = $140.0, Stop Loss = $135.0 (Distance = $5.0)
    # Min order = 0.01 lot = 1 share
    # Risk for 1 share = $5.0 = 175 THB
    res = calculate_position_size(
        symbol="NVDA",
        capital_thb=3000.0,
        entry_price=140.0,
        stop_loss_price=135.0,
        risk_percent=2.0,
        max_leverage=5.0
    )
    assert res["status"] == "OK"
    assert res["shares"] == 1
    assert res["lot_size"] == 0.01
    assert res["notional_thb"] <= 15000.0
    assert res["effective_leverage"] <= 5.0

def test_position_size_leverage_exceeded():
    # Stock price $600.0 -> 1 share = $600 * 35 = 21,000 THB
    # Max notional allowed for 3,000 THB capital at 1:5 leverage is 15,000 THB
    # Must reject as NO_TRADE!
    res = calculate_position_size(
        symbol="EXPENSIVE",
        capital_thb=3000.0,
        entry_price=600.0,
        stop_loss_price=580.0,
        risk_percent=2.0,
        max_leverage=5.0
    )
    assert res["status"] == "NO_TRADE"
    assert "leverage cap" in res["reason"]

def test_position_size_excessive_sl_distance():
    # Stock price $100, Stop Loss $50 (Distance = $50 = 1,750 THB risk for 1 share)
    # 1,750 THB on 3,000 THB capital is > 58% risk! Must reject.
    res = calculate_position_size(
        symbol="VOLATILE",
        capital_thb=3000.0,
        entry_price=100.0,
        stop_loss_price=50.0,
        risk_percent=2.0,
        max_leverage=5.0
    )
    assert res["status"] == "NO_TRADE"
    assert "risk" in res["reason"]

def test_portfolio_limits():
    # Daily loss cap at 5% of 3,000 THB = 150 THB
    res_ok = check_portfolio_risk_limits(capital_thb=3000.0, current_daily_loss_thb=50.0)
    assert res_ok["allowed"] is True

    res_blocked = check_portfolio_risk_limits(capital_thb=3000.0, current_daily_loss_thb=160.0)
    assert res_blocked["allowed"] is False
    assert "Daily loss cap reached" in res_blocked["reason"]
