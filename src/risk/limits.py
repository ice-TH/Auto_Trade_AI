from typing import List, Dict, Any

def check_portfolio_risk_limits(
    capital_thb: float,
    current_daily_loss_thb: float,
    max_daily_loss_percent: float = 5.0,
    open_positions: List[Dict[str, Any]] = None,
    max_open_positions: int = 2,
    max_total_leverage: float = 5.0
) -> Dict[str, Any]:
    """
    Evaluate portfolio-level risk caps before approving new trading plans.
    """
    open_positions = open_positions or []
    max_daily_loss_thb = capital_thb * (max_daily_loss_percent / 100.0)

    # 1. Daily Loss Limit Check
    if current_daily_loss_thb >= max_daily_loss_thb:
        return {
            "allowed": False,
            "reason": f"Daily loss cap reached ({current_daily_loss_thb:.0f} THB >= {max_daily_loss_thb:.0f} THB). All new entries suspended."
        }

    # 2. Maximum Open Positions Check
    if len(open_positions) >= max_open_positions:
        return {
            "allowed": False,
            "reason": f"Maximum simultaneous positions limit ({max_open_positions}) reached."
        }

    # 3. Total Combined Exposure / Leverage Check
    total_open_notional_thb = sum(p.get("notional_thb", 0.0) for p in open_positions)
    max_allowed_notional_thb = capital_thb * max_total_leverage
    if total_open_notional_thb >= max_allowed_notional_thb:
        return {
            "allowed": False,
            "reason": f"Total portfolio notional exposure ({total_open_notional_thb:.0f} THB) exceeds 1:5 leverage cap ({max_allowed_notional_thb:.0f} THB)."
        }

    return {
        "allowed": True,
        "remaining_daily_budget_thb": round(max_daily_loss_thb - current_daily_loss_thb, 2),
        "available_slots": max_open_positions - len(open_positions),
        "remaining_notional_thb": round(max_allowed_notional_thb - total_open_notional_thb, 2)
    }
