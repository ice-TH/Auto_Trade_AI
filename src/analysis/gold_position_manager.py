"""
Gold Position Manager (Unified 1.0R Auto Break-Even Guard)
Monitors open positions for XAU/USD.
1. Primary Rule [XAU-RULE-21]: When floating profit reaches >= +1.0x Initial Risk (1.0R),
   automatically moves Stop Loss to Entry Price +/- (Live Spread + $0.15) to guarantee a Risk-Free Trade.
2. Fallback Rule: If a manual position had no initial SL (or abnormal risk), falls back to $9.00 profit distance.
"""

from typing import Dict, Any, Optional
from src.execution.mt5_client import MT5Client, mt5_client

FALLBACK_TRIGGER_USD = 9.00
FALLBACK_BUFFER_USD = 0.80


def manage_gold_positions(client: Optional[MT5Client] = None, min_r_multiple: float = 1.0) -> Dict[str, Any]:
    """
    Check all open XAU/USD positions and apply unified 1.0R Break-Even SL protection.
    """
    cli = client or mt5_client
    if cli is mt5_client and not cli.is_connected:
        conn = cli.connect()
        if not conn.get("connected") and not cli.simulated_positions:
            return {"status": "SKIPPED", "reason": "MT5 not connected", "actions_taken": []}

    open_positions = cli.get_open_positions()
    gold_positions = [
        p for p in open_positions
        if "XAU" in str(p.get("symbol", "")).upper() or "GOLD" in str(p.get("symbol", "")).upper()
    ]

    if not gold_positions:
        return {"status": "NO_POSITIONS", "actions_taken": [], "active_positions_count": 0}

    actions = []

    # 1. Unified 1.0R R-Multiple Breakeven Engine (matches Web Dashboard behavior)
    locked_results = cli.check_and_apply_breakeven_locks(min_r_multiple=min_r_multiple)
    locked_tickets = set()
    for lr in locked_results:
        sym = str(lr.get("symbol", "")).upper()
        if "XAU" in sym or "GOLD" in sym:
            tkt = lr["ticket"]
            locked_tickets.add(tkt)
            actions.append(
                f"🛡️ Auto Break-Even [{lr['direction']} #{tkt}]: กำไรแตะ +{lr['r_multiple']:.2f}R (>= {min_r_multiple:.1f}R) "
                f"-> ปรับ SL จาก ${lr['previous_sl']:.2f} มาบังหน้าทุนที่ ${lr['new_sl']:.2f} (Risk-Free)"
            )

    # 2. Fallback protection for any manual position opened without initial SL (sl == 0)
    for pos in gold_positions:
        ticket = pos["ticket"]
        if ticket in locked_tickets:
            continue
        direction = str(pos.get("direction", "")).upper()
        open_price = float(pos.get("open_price", 0.0))
        current_price = float(pos.get("current_price", 0.0))
        current_sl = float(pos.get("sl", 0.0))
        current_tp = float(pos.get("tp", 0.0))

        # Only trigger fallback when initial SL was missing
        if current_sl > 0:
            continue

        if direction == "BUY":
            profit_distance = current_price - open_price
            target_be_sl = round(open_price + FALLBACK_BUFFER_USD, 2)
            if profit_distance >= FALLBACK_TRIGGER_USD:
                res = cli.modify_position_sltp(ticket=ticket, sl=target_be_sl, tp=current_tp)
                if res.get("success"):
                    actions.append(
                        f"🛡️ Fallback Break-Even [BUY #{ticket}]: กำไร +${profit_distance:.2f} "
                        f"-> ตั้ง SL บังทุนที่ ${target_be_sl:.2f}"
                    )
        elif direction == "SELL":
            profit_distance = open_price - current_price
            target_be_sl = round(open_price - FALLBACK_BUFFER_USD, 2)
            if profit_distance >= FALLBACK_TRIGGER_USD:
                res = cli.modify_position_sltp(ticket=ticket, sl=target_be_sl, tp=current_tp)
                if res.get("success"):
                    actions.append(
                        f"🛡️ Fallback Break-Even [SELL #{ticket}]: กำไร +${profit_distance:.2f} "
                        f"-> ตั้ง SL บังทุนที่ ${target_be_sl:.2f}"
                    )

    return {
        "status": "COMPLETED",
        "active_positions_count": len(gold_positions),
        "actions_taken": actions
    }
