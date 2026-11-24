"""
Agent Bridge CLI - Tools for Antigravity AI to inspect live MT5 market data,
perform qualitative reasoning, and execute orders directly upon user command.
"""
import sys
import os
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from src.data.base import TimeFrame
from src.data.mt5_adapter import MT5DataAdapter
from src.analysis.zones import build_sr_zones
from src.analysis.indicators import calculate_ema, calculate_atr
from src.strategy.plans import TradingPlan, PlanStatus
from src.strategy.rules import evaluate_bounce_setup
from src.execution.mt5_client import mt5_client

adapter = MT5DataAdapter()

def scan_market(symbols: List[str] = None) -> Dict[str, Any]:
    """Scan MT5 live market and return comprehensive technical state for AI reasoning."""
    target_symbols = symbols or ["XAUUSD", "BTCUSD"]
    conn_status = adapter.get_status()
    
    results = {}
    for sym in target_symbols:
        bars_w = adapter.get_bars(sym, TimeFrame.WEEK, limit=60)
        bars_d = adapter.get_bars(sym, TimeFrame.DAY, limit=150)
        bars_m = adapter.get_bars(sym, TimeFrame.M15, limit=50)
        quote = adapter.get_latest_quote(sym)
        
        if not bars_d:
            results[sym] = {"error": "No bars received from MT5 (is MT5 connected?)"}
            continue

        zones = build_sr_zones(sym, bars_d, n_fractal=3)
        plan = evaluate_bounce_setup(sym, bars_w, bars_d, bars_m, zones, settings)
        
        curr_price = bars_d[-1].close
        ema50 = calculate_ema(bars_d, 50)
        ema200 = calculate_ema(bars_d, 200)
        atr14 = calculate_atr(bars_d, 14)

        results[sym] = {
            "current_price": round(curr_price, 2),
            "quote": quote,
            "ema50": round(ema50[-1]["value"], 2) if ema50 else None,
            "ema200": round(ema200[-1]["value"], 2) if ema200 else None,
            "atr14": round(atr14[-1]["value"], 2) if atr14 else None,
            "active_supports": [{"low": round(z.price_low, 2), "high": round(z.price_high, 2), "touches": z.touch_count} for z in zones if z.zone_type == "SUPPORT"][:3],
            "active_resistances": [{"low": round(z.price_low, 2), "high": round(z.price_high, 2), "touches": z.touch_count} for z in zones if z.zone_type == "RESISTANCE"][:3],
            "plan_status": plan.status.value,
            "setup": {
                "direction": plan.direction,
                "entry_price": plan.entry_price,
                "stop_loss": plan.stop_loss,
                "take_profit": plan.take_profit,
                "risk_reward": plan.risk_reward_ratio,
                "recommended_lot": plan.lot_size,
                "rejection_reason": plan.rejection_reason
            }
        }

    return {
        "mt5_status": conn_status,
        "symbols_data": results
    }

def check_account_and_positions() -> Dict[str, Any]:
    """Retrieve current MT5 account status, balance, equity, and open positions."""
    conn = mt5_client.connect()
    positions = mt5_client.get_open_positions() if conn.get("connected") else []
    return {
        "connection": conn,
        "positions": positions
    }

def execute_order(symbol: str, direction: str, volume: float, sl: float, tp: float, comment: str = "Antigravity AI") -> Dict[str, Any]:
    """Execute order directly through MT5."""
    mt5_client.connect()
    # Resolve broker symbol suffix (e.g. BTCUSD -> BTCUSDm)
    resolved_sym = adapter._resolve_symbol(symbol.upper()) or symbol.upper()
    return mt5_client.send_order(
        symbol=resolved_sym,
        direction=direction.upper(),
        volume=volume,
        sl_price=sl,
        tp_price=tp,
        comment=comment
    )

def close_order(ticket: int) -> Dict[str, Any]:
    return mt5_client.close_position(ticket)

def close_all() -> Dict[str, Any]:
    return mt5_client.emergency_close_all()

def scan_btc_scalp() -> Dict[str, Any]:
    """Experimental 1m Fast Scalper for BTCUSD (Modular - can be safely removed)."""
    try:
        from src.analysis.btc_scalper import scan_btc_1m
        return scan_btc_1m()
    except ImportError:
        return {"error": "BTC scalper module is not installed or has been removed."}

def scan_gold_strategy(manage_limits: bool = True, manage_positions: bool = True, auto_execute_market: bool = False) -> Dict[str, Any]:
    """Experimental Multi-Timeframe Demand & Supply strategy for XAUUSD."""
    try:
        from src.analysis.gold_strategy import scan_gold_setup
        res = scan_gold_setup()
        
        # 1. Manage Active Open Positions (Auto Break-Even Guard)
        if manage_positions:
            try:
                from src.analysis.gold_position_manager import manage_gold_positions
                pos_res = manage_gold_positions()
                res["position_manager"] = pos_res
            except Exception as e:
                res["position_manager"] = {"error": str(e)}

        # 2. Manage Smart Pending Limit Orders
        if manage_limits and "error" not in res:
            try:
                from src.analysis.gold_limit_manager import manage_gold_limits
                limit_res = manage_gold_limits(res)
                res["limit_manager"] = limit_res
            except Exception as e:
                res["limit_manager"] = {"error": str(e)}

        # 3. Auto Execute Valid Market Order if Authorized and Trigger Met
        if auto_execute_market and "error" not in res:
            status = res.get("status", "")
            direction = res.get("recommended_direction", "NEUTRAL")
            entry = res.get("recommended_entry", 0.0)
            sl = res.get("recommended_sl", 0.0)
            tp = res.get("recommended_tp", 0.0)
            sym = res.get("mt5_symbol") or res.get("symbol", "XAUUSDc")
            
            # Actionable market entry setups
            actionable_market_statuses = [
                "BUY_DEMAND_ZONE",
                "SELL_SUPPLY_ZONE",
                "BUY_ROLE_REVERSAL_RETEST",
                "SELL_ROLE_REVERSAL_RETEST"
            ]
            
            if status in actionable_market_statuses and direction in ("BUY", "SELL"):
                # Check if we already have an open position on this symbol to prevent stacking
                cli = mt5_client
                cli.connect()
                open_pos = [p for p in cli.get_open_positions() if sym in p.get("symbol", "")]
                if len(open_pos) == 0:
                    current_login = cli.account_info.get("login") if cli.account_info else None
                    trade_vol = 0.06 if current_login == 160219615 else 0.01
                    exec_comment = f"AutoGold [{status}]"
                    order_res = cli.send_order(
                        symbol=sym,
                        direction=direction,
                        volume=trade_vol,
                        sl_price=sl,
                        tp_price=tp,
                        comment=exec_comment
                    )
                    res["auto_market_execution"] = order_res
                else:
                    res["auto_market_execution"] = {"status": "SKIPPED_ALREADY_OPEN", "open_positions": len(open_pos)}

        return res
    except ImportError as e:
        return {"error": f"Gold strategy module error: {e}"}

def run_gold_loop(interval_sec: float = 60.0, max_iterations: int = 0, auto_execute_market: bool = True):
    """Continuous runner for Gold analysis & limit management & auto order execution."""
    import time
    from datetime import datetime
    iteration = 0
    login = mt5_client.account_info.get("login", 434552387) if mt5_client.is_connected else 434552387
    is_cent = (login == 160219615)
    acc_desc = f"{login} (Real Cent USC)" if is_cent else f"{login} (Demo Sandbox)"
    print(f"================================================================================")
    print(f"  XAU/USD Smart Automation Loop (Interval: {interval_sec}s / {interval_sec/60:.2f}m)")
    print(f"  Target Account: {acc_desc} | Auto Market Order: {auto_execute_market}")
    print(f"================================================================================")
    try:
        while True:
            iteration += 1
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{now_str}] --- Iteration #{iteration} ---")
            res = scan_gold_strategy(manage_limits=True, manage_positions=True, auto_execute_market=auto_execute_market)
            status = res.get("status", "UNKNOWN")
            price = res.get("current_price", 0.0)
            spread = res.get("spread", 0.0)
            limits = res.get("limit_manager", {})
            positions = res.get("position_manager", {})
            auto_exec = res.get("auto_market_execution")
            pos_actions = positions.get("actions_taken", [])
            actions = limits.get("actions_taken", [])
            pending_count = limits.get("active_pending_count", 0)

            print(f"Price: ${price:.2f} | Spread: ${spread:.2f} | Status: {status} | Pending Orders: {pending_count}")
            if pos_actions:
                for pa in pos_actions:
                    print(f"  -> Position Action: {pa}")
            if actions:
                for a in actions:
                    print(f"  -> Limit Action: {a}")
            if auto_exec:
                print(f"  -> Auto Market Order: {auto_exec}")
            if not actions and not pos_actions and not auto_exec:
                print("  -> Actions: No order change needed (positions safe, waiting for zone/trigger).")
            
            if max_iterations > 0 and iteration >= max_iterations:
                print(f"\nCompleted max iterations ({max_iterations}). Exiting loop.")
                break
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\n[XAU/USD Loop] Stopped by user.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Antigravity MT5 Bridge CLI")
    parser.add_argument("action", choices=["scan", "account", "execute", "close", "close-all", "btc-scalp", "gold-strategy", "gold-loop"])
    parser.add_argument("--symbol", type=str, default="")
    parser.add_argument("--direction", type=str, default="BUY")
    parser.add_argument("--volume", type=float, default=0.01)
    parser.add_argument("--sl", type=float, default=0.0)
    parser.add_argument("--tp", type=float, default=0.0)
    parser.add_argument("--ticket", type=int, default=0)
    parser.add_argument("--manage-limits", action="store_true", default=True)
    parser.add_argument("--auto-execute-market", action="store_true", default=False)
    parser.add_argument("--interval", type=float, default=90.0)
    parser.add_argument("--iterations", type=int, default=0)

    args = parser.parse_args()

    if args.action == "scan":
        syms = [args.symbol] if args.symbol else None
        res = scan_market(syms)
        print(json.dumps(res, indent=2))
    elif args.action == "account":
        res = check_account_and_positions()
        print(json.dumps(res, indent=2))
    elif args.action == "execute":
        res = execute_order(args.symbol, args.direction, args.volume, args.sl, args.tp)
        print(json.dumps(res, indent=2))
    elif args.action == "close":
        res = close_order(args.ticket)
        print(json.dumps(res, indent=2))
    elif args.action == "close-all":
        res = close_all()
        print(json.dumps(res, indent=2))
    elif args.action == "btc-scalp":
        res = scan_btc_scalp()
        print(json.dumps(res, indent=2))
    elif args.action == "gold-strategy":
        res = scan_gold_strategy(manage_limits=args.manage_limits, auto_execute_market=args.auto_execute_market)
        print(json.dumps(res, indent=2))
    elif args.action == "gold-loop":
        run_gold_loop(interval_sec=args.interval, max_iterations=args.iterations, auto_execute_market=args.auto_execute_market)
