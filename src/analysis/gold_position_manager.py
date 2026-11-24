"""
Gold Position Manager (Auto Break-Even Guard)
Monitors open positions for XAU/USD. When an order reaches a safe profit threshold (>= $9.00 / ~1.5R),
it automatically adjusts Stop Loss to Entry Price (+ small profit buffer) to create a Risk-Free Trade.
Follows the Set & Forget principle without over-managing TP or micromanaging swings.
"""

from typing import Dict, Any, List
from src.execution.mt5_client import mt5_client

BREAK_EVEN_TRIGGER_USD = 9.00  # Profit threshold (in USD per 1 oz price distance) to trigger BE
BREAK_EVEN_BUFFER_USD = 0.80   # Lock-in buffer to cover broker spread & commission

def manage_gold_positions() -> Dict[str, Any]:
    """
    Check all open XAU/USD positions and apply Break-Even SL protection if criteria met.
    """
    conn = mt5_client.connect()
    if not conn.get("connected"):
        return {"status": "SKIPPED", "reason": "MT5 not connected", "actions_taken": []}

    open_positions = mt5_client.get_open_positions()
    gold_positions = [
        p for p in open_positions
        if "XAU" in p.get("symbol", "").upper() or "GOLD" in p.get("symbol", "").upper()
    ]

    if not gold_positions:
        return {"status": "NO_POSITIONS", "actions_taken": [], "active_positions_count": 0}

    actions = []

    for pos in gold_positions:
        ticket = pos["ticket"]
        direction = pos.get("direction", "").upper()
        open_price = float(pos.get("open_price", 0.0))
        current_price = float(pos.get("current_price", 0.0))
        current_sl = float(pos.get("sl", 0.0))
        current_tp = float(pos.get("tp", 0.0))

        if direction == "BUY":
            profit_distance = current_price - open_price
            # Check if profit threshold reached and SL is not already at or above break-even
            target_be_sl = round(open_price + BREAK_EVEN_BUFFER_USD, 2)
            if profit_distance >= BREAK_EVEN_TRIGGER_USD and (current_sl < target_be_sl):
                res = mt5_client.modify_position_sltp(ticket=ticket, sl=target_be_sl, tp=current_tp)
                if res.get("success"):
                    actions.append(
                        f"🛡️ Auto Break-Even [BUY #{ticket}]: กำไร +${profit_distance:.2f} >= ${BREAK_EVEN_TRIGGER_USD:.2f} "
                        f"-> ปรับ SL จาก ${current_sl:.2f} มาบังทุนที่ ${target_be_sl:.2f} (Risk-Free)"
                    )
                else:
                    actions.append(f"❌ Error adjusting BUY #{ticket}: {res.get('error')}")

        elif direction == "SELL":
            profit_distance = open_price - current_price
            # Check if profit threshold reached and SL is not already at or below break-even
            target_be_sl = round(open_price - BREAK_EVEN_BUFFER_USD, 2)
            if profit_distance >= BREAK_EVEN_TRIGGER_USD and (current_sl == 0.0 or current_sl > target_be_sl):
                res = mt5_client.modify_position_sltp(ticket=ticket, sl=target_be_sl, tp=current_tp)
                if res.get("success"):
                    actions.append(
                        f"🛡️ Auto Break-Even [SELL #{ticket}]: กำไร +${profit_distance:.2f} >= ${BREAK_EVEN_TRIGGER_USD:.2f} "
                        f"-> ปรับ SL จาก ${current_sl:.2f} มาบังทุนที่ ${target_be_sl:.2f} (Risk-Free)"
                    )
                else:
                    actions.append(f"❌ Error adjusting SELL #{ticket}: {res.get('error')}")

    return {
        "status": "COMPLETED",
        "active_positions_count": len(gold_positions),
        "actions_taken": actions
    }
