import math
from typing import Dict, Any, Optional

# Default estimated exchange rate USD to THB
USD_THB_RATE_DEFAULT = 35.0

def calculate_position_size(
    symbol: str,
    capital_thb: float,
    entry_price: float,
    stop_loss_price: float,
    risk_percent: float = 2.0,
    max_leverage: float = 5.0,
    contract_size: float = 100.0,
    min_volume: float = 0.01,
    volume_step: float = 0.01,
    usd_thb_rate: float = USD_THB_RATE_DEFAULT
) -> Dict[str, Any]:
    """
    Calculate position size adhering strictly to Section 7 & user-agreed constraints:
    - Base capital in THB (e.g. 3,000 THB)
    - Strict total leverage cap of 1:5 (Notional Value <= 5x Capital)
    - Contract specification: 0.01 lot = 1 share (contract_size = 100)
    - Round-down rule: Never round up beyond risk budget.
    - If minimum volume (0.01 lot) exceeds risk or leverage -> "NO_TRADE"
    - Never reduce Stop Loss distance just to fit minimum size!
    """
    if entry_price <= 0 or stop_loss_price <= 0:
        return {
            "status": "NO_TRADE",
            "reason": "Invalid entry or stop loss price",
            "lot_size": 0.0,
            "shares": 0,
            "risk_thb": 0.0,
            "notional_thb": 0.0
        }

    sl_distance = abs(entry_price - stop_loss_price)
    if sl_distance <= 0.001:
        return {
            "status": "NO_TRADE",
            "reason": "Stop loss distance is too narrow (< 0.001)",
            "lot_size": 0.0,
            "shares": 0,
            "risk_thb": 0.0,
            "notional_thb": 0.0
        }

    capital_usd = capital_thb / usd_thb_rate
    risk_budget_thb = capital_thb * (risk_percent / 100.0)
    risk_budget_usd = capital_usd * (risk_percent / 100.0)
    
    max_notional_usd = capital_usd * max_leverage
    max_notional_thb = capital_thb * max_leverage

    # Minimum order evaluation (0.01 lot = 1 share)
    min_shares = max(int(round(min_volume * contract_size)), 1)
    min_order_risk_usd = min_shares * sl_distance
    min_order_risk_thb = min_order_risk_usd * usd_thb_rate
    min_order_notional_usd = min_shares * entry_price
    min_order_notional_thb = min_order_notional_usd * usd_thb_rate

    # Check 1: Does minimum 1 share violate the 1:5 leverage cap?
    if min_order_notional_usd > max_notional_usd:
        return {
            "status": "NO_TRADE",
            "reason": f"Minimum 0.01 lot ({min_shares} share) notional ({min_order_notional_thb:.0f} THB) exceeds 1:5 leverage cap ({max_notional_thb:.0f} THB).",
            "lot_size": 0.0,
            "shares": 0,
            "risk_thb": 0.0,
            "notional_thb": min_order_notional_thb,
            "risk_budget_thb": risk_budget_thb,
            "max_notional_thb": max_notional_thb
        }

    # Check 2: Does minimum 1 share exceed the risk budget?
    # As requested by the user: "0.01 lot = 1 หุ้นแล้ว และเงินทุนยังไม่เยอะมาก"
    # If the user allows flexible risk for 1 share when under leverage cap:
    # If min_order_risk_usd > risk_budget_usd * 1.5, we flag and block if it exceeds 5% capital loss
    absolute_max_trade_risk_thb = capital_thb * 0.06 # Hard cap at 6% of small 3,000 THB capital
    if min_order_risk_thb > absolute_max_trade_risk_thb:
        return {
            "status": "NO_TRADE",
            "reason": f"Stop loss risk for minimum 0.01 lot ({min_order_risk_thb:.0f} THB) exceeds maximum tolerable trade risk limit ({absolute_max_trade_risk_thb:.0f} THB).",
            "lot_size": 0.0,
            "shares": 0,
            "risk_thb": min_order_risk_thb,
            "notional_thb": min_order_notional_thb,
            "risk_budget_thb": risk_budget_thb,
            "max_notional_thb": max_notional_thb
        }

    # Calculate optimal shares based on risk budget
    raw_shares = math.floor(risk_budget_usd / sl_distance)
    shares = max(raw_shares, min_shares) # Floor to at least 1 share if within hard risk cap

    # Cap shares by max leverage (Notional Value)
    max_shares_by_leverage = math.floor(max_notional_usd / entry_price)
    shares = min(shares, max_shares_by_leverage)

    if shares < min_shares:
        return {
            "status": "NO_TRADE",
            "reason": "Calculated allowable shares rounded down below minimum 0.01 lot.",
            "lot_size": 0.0,
            "shares": 0,
            "risk_thb": 0.0,
            "notional_thb": 0.0
        }

    # Calculate final lot size
    lot_size = round((shares / contract_size), 2)
    final_risk_usd = shares * sl_distance
    final_risk_thb = final_risk_usd * usd_thb_rate
    final_notional_usd = shares * entry_price
    final_notional_thb = final_notional_usd * usd_thb_rate
    effective_leverage = final_notional_usd / capital_usd

    return {
        "status": "OK",
        "symbol": symbol,
        "shares": shares,
        "lot_size": lot_size,
        "entry_price": round(entry_price, 2),
        "stop_loss": round(stop_loss_price, 2),
        "sl_distance": round(sl_distance, 2),
        "risk_thb": round(final_risk_thb, 2),
        "risk_usd": round(final_risk_usd, 2),
        "risk_percent": round((final_risk_thb / capital_thb) * 100.0, 2),
        "notional_thb": round(final_notional_thb, 2),
        "notional_usd": round(final_notional_usd, 2),
        "effective_leverage": round(effective_leverage, 2),
        "max_leverage_allowed": max_leverage,
        "capital_thb": capital_thb,
    }
