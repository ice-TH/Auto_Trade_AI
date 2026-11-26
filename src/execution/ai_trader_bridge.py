"""
Standalone CLI Bridge, Hard Risk Gate, and 20s Event-Driven Wakeup Radar for XAU/USD AI Trader Mode (Mode 2).
Designed for 0% modification to Mode 1 (`agent_bridge.py` / `gold-loop`).
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.base import TimeFrame
from src.data.mt5_adapter import MT5DataAdapter
from src.execution.mt5_client import MT5Client, mt5_client
from src.analysis.gold_strategy import MAX_GOLD_SL_USD, MIN_GOLD_RR_RATIO, scan_gold_setup
from src.analysis.gold_position_manager import manage_gold_positions
from src.analysis.gold_ai_context import (
    build_gold_ai_context,
    extract_fresh_m5_zones,
    render_gold_ai_chart,
)
from src.risk.news_guard import (
    TZ_BANGKOK,
    is_news_blackout,
    is_rollover_blackout,
    is_spread_acceptable,
    is_volatility_spike,
)

MAX_ALLOWED_SPREAD_USD = 0.40
MAX_AI_LIMIT_RENEWALS = 5
MAX_LIMIT_DRIFT_ATR = 2.0

_AI_LIMIT_RENEWALS: Dict[int, int] = {}


def _open_gold_positions(cli: MT5Client) -> List[Dict[str, Any]]:
    return [
        p for p in (cli.get_open_positions() or [])
        if any(k in str(p.get("symbol", "")).upper() for k in ("XAU", "GOLD"))
    ]


def _pending_gold_orders(cli: MT5Client) -> List[Dict[str, Any]]:
    return [
        o for o in (cli.get_pending_orders() or [])
        if any(k in str(o.get("symbol", "")).upper() for k in ("XAU", "GOLD"))
    ]


def _resolve_gold_account_and_symbol(cli: MT5Client, adapter: Optional[MT5DataAdapter] = None) -> Dict[str, Any]:
    if cli is mt5_client and not cli.is_connected:
        cli.connect()
    login = cli.account_info.get("login") if cli.account_info else None
    if login == 160219615:
        return {"login": login, "symbol": "XAUUSDc", "locked_volume": 0.06}
    adp = adapter or MT5DataAdapter()
    resolved = adp._resolve_symbol("XAUUSD") if cli.is_connected else "XAUUSDm"
    return {"login": login or 434552387, "symbol": resolved or "XAUUSDm", "locked_volume": 0.01}


def validate_ai_gold_order(
    order_kind: str,  # "MARKET" or "LIMIT"
    direction: str,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    current_price: float,
    spread: float,
    client: Optional[MT5Client] = None,
    adapter: Optional[MT5DataAdapter] = None,
) -> Dict[str, Any]:
    """
    Hard Risk Gate enforced strictly in code before ANY AI Trader order reaches MT5:
    1. Locks Lot Size (0.06 on Cent #160219615, 0.01 on Demo) & Symbol Whitelist
    2. Enforces Single-Position Guard (max 1 open Gold position)
    3. Blocks News Blackout, Rollover Blackout, and Spread > $0.40
    4. Enforces Hard SL > 0, directional geometry, SL Distance <= $8.00, and R:R >= 1.50
    """
    cli = client or mt5_client
    acc_spec = _resolve_gold_account_and_symbol(cli, adapter=adapter)
    dir_up = str(direction or "").upper()
    kind_up = str(order_kind or "MARKET").upper()

    if dir_up not in ("BUY", "SELL"):
        return {"valid": False, "code": "INVALID_DIRECTION", "reason": f"Direction must be BUY or SELL (got {direction})"}

    # 1. Single-Position Guard
    open_pos = _open_gold_positions(cli)
    if len(open_pos) > 0:
        return {
            "valid": False,
            "code": "BLOCKED_SINGLE_POSITION",
            "reason": f"Single-Position Guard: มีไม้ทองคำเปิดอยู่แล้ว ({len(open_pos)} ไม้, Ticket #{open_pos[0].get('ticket')}) ห้ามเปิดซ้อน",
        }

    # 2. News / Rollover / Spread Guards
    in_news, news_msg = is_news_blackout()
    if in_news:
        return {"valid": False, "code": "BLOCKED_NEWS_BLACKOUT", "reason": news_msg}

    in_roll, roll_msg = is_rollover_blackout()
    if in_roll:
        return {"valid": False, "code": "BLOCKED_ROLLOVER_BLACKOUT", "reason": roll_msg}

    spread_ok, spread_msg = is_spread_acceptable(spread, max_allowed_spread=MAX_ALLOWED_SPREAD_USD)
    if not spread_ok:
        return {"valid": False, "code": "BLOCKED_SPREAD_GUARD", "reason": spread_msg}

    # 3. SL/TP Geometry & Limit Placement Validity
    if sl_price <= 0 or tp_price <= 0 or entry_price <= 0:
        return {"valid": False, "code": "MISSING_SL_OR_TP", "reason": "Entry, Hard Stop Loss, and Take Profit must all be > 0."}

    if dir_up == "BUY":
        if not (sl_price < entry_price < tp_price):
            return {
                "valid": False,
                "code": "INVALID_BUY_GEOMETRY",
                "reason": f"BUY requires SL (${sl_price:.2f}) < Entry (${entry_price:.2f}) < TP (${tp_price:.2f}).",
            }
        if kind_up == "LIMIT" and current_price > 0 and entry_price >= current_price:
            return {
                "valid": False,
                "code": "INVALID_BUY_LIMIT_PRICE",
                "reason": f"BUY_LIMIT price (${entry_price:.2f}) must be strictly below current price (${current_price:.2f}).",
            }
    else:
        if not (tp_price < entry_price < sl_price):
            return {
                "valid": False,
                "code": "INVALID_SELL_GEOMETRY",
                "reason": f"SELL requires TP (${tp_price:.2f}) < Entry (${entry_price:.2f}) < SL (${sl_price:.2f}).",
            }
        if kind_up == "LIMIT" and current_price > 0 and entry_price <= current_price:
            return {
                "valid": False,
                "code": "INVALID_SELL_LIMIT_PRICE",
                "reason": f"SELL_LIMIT price (${entry_price:.2f}) must be strictly above current price (${current_price:.2f}).",
            }

    # 4. Hard SL Cap (<= $8.00) & Minimum R:R (>= 1.50)
    sl_dist = round(abs(entry_price - sl_price), 2)
    tp_dist = round(abs(tp_price - entry_price), 2)
    if sl_dist < 0.20:
        return {"valid": False, "code": "REJECTED_SL_TOO_TIGHT", "reason": f"SL distance (${sl_dist:.2f}) is unrealistically tight (< $0.20)."}
    if sl_dist > MAX_GOLD_SL_USD:
        return {
            "valid": False,
            "code": "REJECTED_SL_TOO_WIDE",
            "reason": f"Hard SL Cap: ระยะ SL ${sl_dist:.2f} เกินเพดานปลอดภัย ${MAX_GOLD_SL_USD:.2f} USD",
        }

    rr = round(tp_dist / sl_dist, 2)
    if rr < MIN_GOLD_RR_RATIO:
        return {
            "valid": False,
            "code": "REJECTED_POOR_RR",
            "reason": f"Minimum R:R Guard: R:R {rr:.2f} ต่ำกว่าเกณฑ์ขั้นต่ำ {MIN_GOLD_RR_RATIO:.2f}",
        }

    return {
        "valid": True,
        "code": "PASSED_HARD_RISK_GATE",
        "symbol": acc_spec["symbol"],
        "locked_volume": acc_spec["locked_volume"],
        "direction": dir_up,
        "entry": round(entry_price, 2),
        "sl": round(sl_price, 2),
        "tp": round(tp_price, 2),
        "sl_distance": sl_dist,
        "tp_distance": tp_dist,
        "rr_ratio": rr,
    }


def _live_price_and_spread(cli: MT5Client, symbol: str, direction: str) -> Dict[str, float]:
    if cli.is_connected:
        q = cli.get_symbol_quote(symbol)
        if "error" not in q:
            bid = float(q.get("bid") or 0.0)
            ask = float(q.get("ask") or 0.0)
            sp = float(q.get("spread") or 0.20)
            px = ask if direction.upper() == "BUY" else bid
            return {"price": px, "mid": round((bid + ask) / 2.0, 2), "spread": sp}
    setup = scan_gold_setup()
    px = float(setup.get("current_price") or 3600.0)
    sp = float(setup.get("spread") or 0.20)
    return {"price": px, "mid": px, "spread": sp}


def _save_execution_visual_audit(
    symbol: str,
    event_tag: str,
    planned_trade: Dict[str, Any],
    reason: str,
    order_result: Dict[str, Any],
    base_screenshots_dir: Optional[Path] = None,
) -> Optional[Dict[str, str]]:
    try:
        adp = MT5DataAdapter()
        setup = scan_gold_setup()
        bars_15m = adp.get_bars(symbol, TimeFrame.M15, limit=100)
        bars_5m = adp.get_bars(symbol, TimeFrame.M5, limit=60)
        return render_gold_ai_chart(
            symbol=symbol,
            bars_15m=bars_15m,
            bars_5m=bars_5m,
            setup_data=setup,
            event_tag=event_tag,
            planned_trade=planned_trade,
            ai_note=reason,
            extra_audit={"order_result": order_result},
            base_screenshots_dir=base_screenshots_dir,
        )
    except Exception as exc:
        return {"audit_warning": f"Chart audit skipped: {exc}"}


def ai_place_market(
    direction: str,
    sl: float,
    tp: float,
    reason: str = "AI Trader Market Entry",
    client: Optional[MT5Client] = None,
    price_override: Optional[float] = None,
    spread_override: Optional[float] = None,
    save_chart: bool = True,
    base_screenshots_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    cli = client or mt5_client
    spec = _resolve_gold_account_and_symbol(cli)
    symbol = spec["symbol"]
    mkt = _live_price_and_spread(cli, symbol, direction)
    entry_px = price_override if price_override is not None else mkt["price"]
    spread = spread_override if spread_override is not None else mkt["spread"]

    gate = validate_ai_gold_order(
        order_kind="MARKET",
        direction=direction,
        entry_price=entry_px,
        sl_price=sl,
        tp_price=tp,
        current_price=entry_px,
        spread=spread,
        client=cli,
    )
    if not gate["valid"]:
        return {"success": False, "gate": gate}

    # Cancel any leftover Gold pending orders before/after market fill to prevent double exposure
    cancelled_pending = []
    for po in _pending_gold_orders(cli):
        c_res = cli.cancel_pending_order(po["ticket"])
        if c_res.get("success"):
            cancelled_pending.append(po["ticket"])
            _AI_LIMIT_RENEWALS.pop(po["ticket"], None)

    order_res = cli.send_order(
        symbol=gate["symbol"],
        direction=gate["direction"],
        volume=gate["locked_volume"],
        sl_price=gate["sl"],
        tp_price=gate["tp"],
        comment=f"AITrader MKT [{gate['rr_ratio']:.1f}R]",
    )
    audit = None
    if save_chart and order_res.get("success"):
        audit = _save_execution_visual_audit(
            symbol=gate["symbol"],
            event_tag=f"MARKET_{gate['direction']}",
            planned_trade={"entry": order_res.get("price", gate["entry"]), "sl": gate["sl"], "tp": gate["tp"]},
            reason=reason,
            order_result=order_res,
            base_screenshots_dir=base_screenshots_dir,
        )
    return {
        "success": bool(order_res.get("success")),
        "gate": gate,
        "cancelled_stale_limits": cancelled_pending,
        "order": order_res,
        "reason": reason,
        "visual_audit": audit,
    }


def ai_place_limit(
    direction: str,
    price: float,
    sl: float,
    tp: float,
    ttl_minutes: int = 15,
    reason: str = "AI Trader Limit Pre-placement",
    client: Optional[MT5Client] = None,
    current_price_override: Optional[float] = None,
    spread_override: Optional[float] = None,
    save_chart: bool = True,
    base_screenshots_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    cli = client or mt5_client
    spec = _resolve_gold_account_and_symbol(cli)
    symbol = spec["symbol"]
    mkt = _live_price_and_spread(cli, symbol, direction)
    curr_px = current_price_override if current_price_override is not None else mkt["mid"]
    spread = spread_override if spread_override is not None else mkt["spread"]

    gate = validate_ai_gold_order(
        order_kind="LIMIT",
        direction=direction,
        entry_price=price,
        sl_price=sl,
        tp_price=tp,
        current_price=curr_px,
        spread=spread,
        client=cli,
    )
    if not gate["valid"]:
        return {"success": False, "gate": gate}

    ttl_clamped = max(5, min(int(ttl_minutes), 30))

    # Replace any existing Gold pending order cleanly (Single-Pending rule)
    replaced_tickets = []
    for po in _pending_gold_orders(cli):
        c_res = cli.cancel_pending_order(po["ticket"])
        if c_res.get("success"):
            replaced_tickets.append(po["ticket"])
            _AI_LIMIT_RENEWALS.pop(po["ticket"], None)

    order_res = cli.send_limit_order(
        symbol=gate["symbol"],
        direction=gate["direction"],
        volume=gate["locked_volume"],
        price=gate["entry"],
        sl_price=gate["sl"],
        tp_price=gate["tp"],
        expiry_minutes=ttl_clamped,
        comment=f"AITrader LMT [{gate['rr_ratio']:.1f}R]",
    )
    if order_res.get("success") and order_res.get("ticket"):
        _AI_LIMIT_RENEWALS[int(order_res["ticket"])] = 0

    audit = None
    if save_chart and order_res.get("success"):
        audit = _save_execution_visual_audit(
            symbol=gate["symbol"],
            event_tag=f"LIMIT_{gate['direction']}",
            planned_trade={"entry": gate["entry"], "sl": gate["sl"], "tp": gate["tp"]},
            reason=reason,
            order_result=order_res,
            base_screenshots_dir=base_screenshots_dir,
        )
    return {
        "success": bool(order_res.get("success")),
        "gate": gate,
        "replaced_pending_tickets": replaced_tickets,
        "order": order_res,
        "reason": reason,
        "visual_audit": audit,
    }


def ai_modify_sltp(
    ticket: int,
    sl: float,
    tp: float,
    reason: str = "AI Trader SL/TP Management",
    client: Optional[MT5Client] = None,
) -> Dict[str, Any]:
    cli = client or mt5_client
    if cli is mt5_client and not cli.is_connected:
        cli.connect()

    if sl <= 0:
        return {"success": False, "error": "Hard SL > 0 is mandatory; removing SL is prohibited."}

    pos = next((p for p in _open_gold_positions(cli) if int(p["ticket"]) == int(ticket)), None)
    if not pos:
        return {"success": False, "error": f"Open Gold position #{ticket} not found."}

    open_px = float(pos.get("open_price") or 0.0)
    curr_px = float(pos.get("current_price") or 0.0)
    direction = str(pos.get("direction", "BUY")).upper()

    if direction == "BUY":
        if curr_px > 0 and sl >= curr_px:
            return {"success": False, "error": f"BUY SL (${sl:.2f}) must be below current price (${curr_px:.2f})."}
        if open_px > 0 and (open_px - sl) > MAX_GOLD_SL_USD:
            return {"success": False, "error": f"Widening risk beyond ${MAX_GOLD_SL_USD:.2f} from entry (${open_px:.2f}) is prohibited."}
    else:
        if curr_px > 0 and sl <= curr_px:
            return {"success": False, "error": f"SELL SL (${sl:.2f}) must be above current price (${curr_px:.2f})."}
        if open_px > 0 and (sl - open_px) > MAX_GOLD_SL_USD:
            return {"success": False, "error": f"Widening risk beyond ${MAX_GOLD_SL_USD:.2f} from entry (${open_px:.2f}) is prohibited."}

    final_tp = float(tp) if tp > 0 else float(pos.get("tp") or 0.0)
    res = cli.modify_position_sltp(ticket=ticket, sl=round(sl, 2), tp=round(final_tp, 2))
    res["reason"] = reason
    return res


def ai_cancel_limits(
    ticket: int = 0,
    reason: str = "AI Trader Cancel Pending",
    client: Optional[MT5Client] = None,
) -> Dict[str, Any]:
    cli = client or mt5_client
    if cli is mt5_client and not cli.is_connected:
        cli.connect()

    targets = _pending_gold_orders(cli)
    if ticket > 0:
        targets = [o for o in targets if int(o["ticket"]) == int(ticket)]

    cancelled = []
    errors = []
    for o in targets:
        tkt = int(o["ticket"])
        res = cli.cancel_pending_order(tkt)
        if res.get("success"):
            cancelled.append(tkt)
            _AI_LIMIT_RENEWALS.pop(tkt, None)
        else:
            errors.append({"ticket": tkt, "error": res.get("error")})

    return {"success": len(errors) == 0, "cancelled_tickets": cancelled, "errors": errors, "reason": reason}


def ai_close_position(
    ticket: int,
    reason: str = "AI Trader Early Exit",
    client: Optional[MT5Client] = None,
    sync_journal: bool = True,
) -> Dict[str, Any]:
    cli = client or mt5_client
    if cli is mt5_client and not cli.is_connected:
        cli.connect()

    res = cli.close_position(ticket)
    res["reason"] = reason
    if res.get("success") and sync_journal:
        try:
            from src.analysis.trade_reviewer import sync_and_review_all
            res["journal_sync"] = sync_and_review_all()
        except Exception as exc:
            res["journal_sync"] = {"warning": str(exc)}
    return res


def _detect_direct_m5_impulse(bars_5m: List[Any], curr_atr: float) -> Dict[str, bool]:
    """
    Direct M5 violent candle check (independent of EA zone-touch status) so pending Limits
    are immediately pulled if a heavy marubozu slams toward the order between poll cycles.
    """
    if not bars_5m:
        return {"bear_knife": False, "bull_rocket": False}
    m5_atr = max(curr_atr * 0.60, 0.80)
    recent_2 = bars_5m[-2:] if len(bars_5m) >= 2 else bars_5m[-1:]
    bear_knife = False
    bull_rocket = False
    for b in recent_2:
        rng = max(float(b.high) - float(b.low), 0.001)
        body = float(b.close) - float(b.open)
        if body < 0 and (rng >= 1.75 * m5_atr) and (abs(body) / rng >= 0.70):
            bear_knife = True
        if body > 0 and (rng >= 1.75 * m5_atr) and (abs(body) / rng >= 0.70):
            bull_rocket = True
    return {"bear_knife": bear_knife, "bull_rocket": bull_rocket}


def protect_ai_pending_limits(
    setup: Dict[str, Any],
    cli: MT5Client,
    bars_5m_override: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Watchdog-only protection for AI's pending orders:
    - Cancels immediately on open position, News/Rollover blackout, Spread > $0.40,
      Volatility spike, Falling Knife / Rocket Surge, direct M5 violent impulse near limit,
      structural break, or excessive drift.
    - Renews Dead Man's Switch lease (up to 5 renewals) if safe.
    - NEVER places any new order!
    """
    pending = _pending_gold_orders(cli)
    if not pending:
        return {"cancelled": [], "renewed": [], "actions": []}

    open_pos = _open_gold_positions(cli)
    has_open = len(open_pos) > 0
    curr_price = float(setup.get("current_price") or 0.0)
    curr_atr = float(setup.get("current_atr") or 3.0)
    live_range = float(setup.get("live_bar_range") or 0.0)
    spread = float(setup.get("spread") or 0.20)
    status = setup.get("status", "")
    symbol = setup.get("mt5_symbol") or setup.get("symbol") or "XAUUSDc"

    bars_5m: List[Any] = []
    if bars_5m_override is not None:
        bars_5m = bars_5m_override
    elif cli.is_connected:
        try:
            bars_5m = MT5DataAdapter().get_bars(symbol, TimeFrame.M5, limit=4)
        except Exception:
            bars_5m = []
    m5_imp = _detect_direct_m5_impulse(bars_5m, curr_atr)

    in_news, news_reason = is_news_blackout()
    in_roll, roll_reason = is_rollover_blackout()
    spread_ok, spread_reason = is_spread_acceptable(spread, max_allowed_spread=MAX_ALLOWED_SPREAD_USD)
    in_spike, spike_reason = is_volatility_spike(live_range, curr_atr, spike_multiplier=2.2)

    cancelled: List[int] = []
    renewed: List[int] = []
    actions: List[str] = []

    for o in pending:
        tkt = int(o["ticket"])
        odir = str(o.get("direction", "")).upper()
        oprice = float(o.get("price") or 0.0)
        osl = float(o.get("sl") or 0.0)
        otp = float(o.get("tp") or 0.0)
        near_limit = (curr_price > 0 and oprice > 0 and abs(curr_price - oprice) <= max(0.55 * curr_atr, 2.50))

        cancel_why = None
        if has_open:
            cancel_why = "Single-Position Guard: มีไม้ทองคำเปิดอยู่แล้ว"
        elif in_news:
            cancel_why = news_reason
        elif in_roll:
            cancel_why = roll_reason
        elif not spread_ok:
            cancel_why = spread_reason
        elif in_spike:
            cancel_why = spike_reason
        elif odir == "BUY" and (status == "REJECTED_FALLING_KNIFE" or (near_limit and m5_imp["bear_knife"])):
            cancel_why = "ตรวจพบแท่งเทียนมีดตก/M5 ทุบแรงใกล้จุดเข้า ชัก Buy Limit หนีทันที"
        elif odir == "SELL" and (status == "REJECTED_ROCKET_SURGE" or (near_limit and m5_imp["bull_rocket"])):
            cancel_why = "ตรวจพบแท่งเทียนพุ่งแรง/M5 กระชากใกล้จุดเข้า ชัก Sell Limit หนีทันที"
        elif odir == "BUY" and osl > 0 and curr_price > 0 and curr_price <= osl:
            cancel_why = f"ราคาหลุดแนว SL (${curr_price:.2f} <= ${osl:.2f}) โครงสร้างเสีย"
        elif odir == "SELL" and osl > 0 and curr_price > 0 and curr_price >= osl:
            cancel_why = f"ราคาทะลุแนว SL (${curr_price:.2f} >= ${osl:.2f}) โครงสร้างเสีย"
        elif odir == "BUY" and otp > 0 and curr_price > 0 and curr_price >= otp:
            cancel_why = f"ราคาวิ่งถึงเป้า TP (${curr_price:.2f} >= ${otp:.2f}) โดยไม่เกี่ยวไม้ — ยกเลิกเพื่อหาจุดเข้าใหม่"
        elif odir == "SELL" and otp > 0 and curr_price > 0 and curr_price <= otp:
            cancel_why = f"ราคาวิ่งถึงเป้า TP (${curr_price:.2f} <= ${otp:.2f}) โดยไม่เกี่ยวไม้ — ยกเลิกเพื่อหาจุดเข้าใหม่"
        elif curr_price > 0 and oprice > 0 and abs(curr_price - oprice) > (MAX_LIMIT_DRIFT_ATR * curr_atr):
            cancel_why = f"ราคาวิ่งห่างจาก Limit เกิน {MAX_LIMIT_DRIFT_ATR}x ATR"

        if cancel_why:
            c_res = cli.cancel_pending_order(tkt)
            if c_res.get("success"):
                cancelled.append(tkt)
                _AI_LIMIT_RENEWALS.pop(tkt, None)
                actions.append(f"EMERGENCY_CANCEL #{tkt}: {cancel_why}")
            continue

        # Renew lease if approaching expiration (< 240s left) or simulated order
        exp_ts = o.get("expiration")
        now_ts = int(datetime.now(timezone.utc).timestamp())
        should_renew = False
        if isinstance(exp_ts, (int, float)) and exp_ts > 0:
            should_renew = (exp_ts - now_ts) <= 240
        elif o.get("expiry_time"):
            try:
                dt_exp = datetime.fromisoformat(str(o["expiry_time"]).replace("Z", "+00:00"))
                should_renew = (dt_exp.timestamp() - now_ts) <= 240
            except Exception:
                should_renew = False

        if should_renew:
            used = _AI_LIMIT_RENEWALS.get(tkt, 0)
            if used >= MAX_AI_LIMIT_RENEWALS:
                if cli.cancel_pending_order(tkt).get("success"):
                    cancelled.append(tkt)
                    _AI_LIMIT_RENEWALS.pop(tkt, None)
                    actions.append(f"EXPIRED_MAX_RENEWALS #{tkt}: ครบโควตาต่อเวลา {MAX_AI_LIMIT_RENEWALS} รอบ")
            else:
                if cli.renew_pending_order_expiry(tkt, additional_minutes=15).get("success"):
                    _AI_LIMIT_RENEWALS[tkt] = used + 1
                    renewed.append(tkt)
                    actions.append(f"RENEWED_LEASE #{tkt}: ต่ออายุ 15 นาที ({used + 1}/{MAX_AI_LIMIT_RENEWALS})")

    return {"cancelled": cancelled, "renewed": renewed, "actions": actions}


def _seconds_to_next_m5_close(now_utc: Optional[datetime] = None, buffer_sec: float = 3.0) -> float:
    dt = now_utc or datetime.now(timezone.utc)
    elapsed_in_bar = (dt.minute % 5) * 60 + dt.second + (dt.microsecond / 1_000_000.0)
    rem = 300.0 - elapsed_in_bar + buffer_sec
    return round(max(10.0, rem), 1)


def _check_pending_limit_approach(
    pending_orders: List[Dict[str, Any]],
    setup: Dict[str, Any],
    limit_approach_atr: float,
    guard_ticket: int = 0,
) -> Optional[Dict[str, Any]]:
    curr_price = float(setup.get("current_price") or 0.0)
    curr_atr = float(setup.get("current_atr") or 3.0)
    if curr_price <= 0 or not pending_orders:
        return None

    threshold = max(1.50, max(0.0, limit_approach_atr) * max(curr_atr, 1.0))
    for o in pending_orders:
        tkt = int(o["ticket"])
        if guard_ticket > 0 and tkt == int(guard_ticket):
            continue
        oprice = float(o.get("price") or 0.0)
        odir = str(o.get("direction", "")).upper()
        if oprice <= 0:
            continue
        dist = abs(curr_price - oprice)
        if dist <= threshold:
            return {
                "ticket": tkt,
                "direction": odir,
                "price": oprice,
                "sl": float(o.get("sl") or 0.0),
                "tp": float(o.get("tp") or 0.0),
                "distance_usd": round(dist, 2),
                "threshold_usd": round(threshold, 2),
                "detail": (
                    f"ราคาเข้าใกล้ {odir} Limit #{tkt} ที่ ${oprice:.2f} "
                    f"(ปัจจุบัน ${curr_price:.2f}, ห่าง ${dist:.2f} <= ${threshold:.2f}) — ปลุก AI ตรวจแท่งเทียน/ข่าวก่อนแมตช์"
                ),
            }
    return None


def _check_zone_proximity(
    setup: Dict[str, Any],
    proximity_atr: float,
    pending_orders: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    curr_price = float(setup.get("current_price") or 0.0)
    curr_atr = float(setup.get("current_atr") or 3.0)
    if curr_price <= 0 or curr_atr <= 0:
        return None

    pending_dirs = {str(o.get("direction", "")).upper() for o in (pending_orders or [])}

    nd = setup.get("nearest_demand")
    if nd and "BUY" not in pending_dirs:
        zl, zh = float(nd["zone_low"]), float(nd["zone_high"])
        if (zl - 0.35 * curr_atr) <= curr_price <= (zh + proximity_atr * curr_atr):
            return f"ราคาจ่อโซน Demand ({nd.get('pattern')} ${zl:.2f}-${zh:.2f}, ปัจจุบัน ${curr_price:.2f})"

    ns = setup.get("nearest_supply")
    if ns and "SELL" not in pending_dirs:
        zl, zh = float(ns["zone_low"]), float(ns["zone_high"])
        if (zl - proximity_atr * curr_atr) <= curr_price <= (zh + 0.35 * curr_atr):
            return f"ราคาจ่อโซน Supply ({ns.get('pattern')} ${zl:.2f}-${zh:.2f}, ปัจจุบัน ${curr_price:.2f})"

    if not pending_dirs:
        status = str(setup.get("status", ""))
        if "ROLE_REVERSAL" in status or status in ("BUY_DEMAND_ZONE", "SELL_SUPPLY_ZONE"):
            return f"ตรวจพบสัญญาณโครงสร้าง {status} ที่ ${curr_price:.2f}"

    return None


def _check_m5_zone_proximity(
    bars_5m: List[Any],
    setup: Dict[str, Any],
    pending_orders: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    curr_price = float(setup.get("current_price") or 0.0)
    curr_atr = float(setup.get("current_atr") or 3.0)
    if curr_price <= 0 or curr_atr <= 0 or not bars_5m:
        return None

    m5_atr = max(curr_atr * 0.60, 0.80)
    prox_band = max(2.50, 0.45 * m5_atr)
    pending_dirs = {str(o.get("direction", "")).upper() for o in (pending_orders or [])}
    m5_map = extract_fresh_m5_zones(bars_5m, curr_price, curr_atr)

    md = m5_map.get("nearest_m5_demand")
    if md and "BUY" not in pending_dirs:
        zl, zh = float(md["zone_low"]), float(md["zone_high"])
        opp_s = [
            float(s["zone_low"])
            for s in (m5_map.get("nearest_m5_supply"), setup.get("nearest_supply"))
            if s and float(s["zone_low"]) > zh
        ]
        headroom = (min(opp_s) - zh) if opp_s else 999.0
        min_req_space = max((zh - zl + 1.0) * MIN_GOLD_RR_RATIO, 4.50)
        if headroom >= min_req_space and (zl - 0.25 * m5_atr) <= curr_price <= (zh + prox_band):
            return f"ราคาจ่อโซนย่อย M5 Demand ({md.get('pattern')} ${zl:.2f}-${zh:.2f}, ปัจจุบัน ${curr_price:.2f})"

    ms = m5_map.get("nearest_m5_supply")
    if ms and "SELL" not in pending_dirs:
        zl, zh = float(ms["zone_low"]), float(ms["zone_high"])
        opp_d = [
            float(d["zone_high"])
            for d in (m5_map.get("nearest_m5_demand"), setup.get("nearest_demand"))
            if d and float(d["zone_high"]) < zl
        ]
        headroom = (zl - max(opp_d)) if opp_d else 999.0
        min_req_space = max((zh - zl + 1.0) * MIN_GOLD_RR_RATIO, 4.50)
        if headroom >= min_req_space and (zl - prox_band) <= curr_price <= (zh + 0.25 * m5_atr):
            return f"ราคาจ่อโซนย่อย M5 Supply ({ms.get('pattern')} ${zl:.2f}-${zh:.2f}, ปัจจุบัน ${curr_price:.2f})"

    return None


def wait_for_trigger(
    poll_sec: float = 20.0,
    max_wait_sec: float = 900.0,
    proximity_atr: float = 0.80,
    limit_approach_atr: float = 0.35,
    displacement_atr: float = 1.0,
    guard_ticket: int = 0,
    sniper_m5: bool = False,
    sync_next_m5: bool = False,
    log_progress: bool = True,
    client: Optional[MT5Client] = None,
    setup_fn: Callable[[], Dict[str, Any]] = scan_gold_setup,
    bars_5m_fn: Optional[Callable[[str], List[Any]]] = None,
    context_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    """
    Event-Driven 20s Radar & Safety Watchdog for Antigravity Chat Reactive Wakeup:
    - Runs locally every `poll_sec` (0 AI tokens while waiting) and emits live telemetry to stderr.
    - Auto-locks +1.0R Break-Even and protects AI's Pending Limits on every cycle.
    - Immediately returns/exits to wake Antigravity Chat when:
      1) ORDER_FILLED / POSITION_CLOSED / LIMIT_EMERGENCY_CANCELLED / LIMIT_EXPIRED_ON_BROKER
      2) LIMIT_APPROACHING (pre-fill wakeup when price is within `limit_approach_atr` of Pending Limit, unless `guard_ticket` already verified)
      3) ZONE_PROXIMITY (when flat & not already in sniper-m5 wait)
      4) OPEN_POSITION_VOLATILITY_ALERT while holding a position
      5) SNIPER_M5_BAR_CHECK / HEARTBEAT_TIMEOUT (`max_wait_sec` reached)
    """
    cli = client or mt5_client
    if cli is mt5_client and not cli.is_connected:
        cli.connect()

    if sync_next_m5:
        sniper_m5 = True
        max_wait_sec = _seconds_to_next_m5_close()

    init_open_tickets = {int(p["ticket"]) for p in _open_gold_positions(cli)}
    init_pending_tickets = {int(o["ticket"]) for o in _pending_gold_orders(cli)}

    if log_progress:
        print(
            f"[AI-Radar] Started | poll={poll_sec:.0f}s | max_wait={max_wait_sec:.0f}s | "
            f"prox={proximity_atr:.2f}xATR | limit_approach={limit_approach_atr:.2f}xATR | "
            f"disp={displacement_atr:.2f}xATR | guard_ticket={guard_ticket or 'none'} | sniper_m5={sniper_m5}",
            file=sys.stderr,
            flush=True,
        )

    start_mono = time.monotonic()
    elapsed = 0.0
    accumulated_actions: List[str] = []
    wake_reason = "HEARTBEAT_TIMEOUT"
    wake_detail = f"ครบกำหนดรอบตรวจปกติ ({int(max_wait_sec)} วินาที)"
    journal_sync_res = None
    last_setup: Dict[str, Any] = {}
    planned_trade_overlay: Optional[Dict[str, Any]] = None
    start_price: Optional[float] = None
    init_m5_bar_time: Any = None
    init_live_rng: float = 0.0
    momentum_spike_triggered: bool = False
    poll_iter = 0

    while True:
        last_setup = setup_fn()
        symbol = str(last_setup.get("mt5_symbol") or last_setup.get("symbol") or "XAUUSDc")
        # Ensure last_setup has fresh live price directly from broker quote if available
        if cli.is_connected:
            try:
                _q = cli.symbol_info_tick(symbol)
                if _q and _q.get("bid"):
                    last_setup["current_price"] = float(_q["bid"])
            except Exception:
                pass

        bars_5m: List[Any] = []
        if bars_5m_fn is not None:
            bars_5m = bars_5m_fn(symbol) or []
        elif cli.is_connected:
            try:
                bars_5m = MT5DataAdapter().get_bars(symbol, TimeFrame.M5, limit=60) or []
            except Exception:
                bars_5m = []

        # 1. Unified +1.0R Auto Break-Even Guard
        pos_guard = manage_gold_positions(client=cli)
        for act in pos_guard.get("actions_taken", []):
            accumulated_actions.append(act)

        # 2. Protect AI's Pending Limits (Watchdog only — never places new orders!)
        lim_guard = protect_ai_pending_limits(
            last_setup,
            cli,
            bars_5m_override=bars_5m[-4:] if bars_5m else None,
        )
        for act in lim_guard.get("actions", []):
            accumulated_actions.append(act)

        live_open = _open_gold_positions(cli)
        live_pendings = _pending_gold_orders(cli)
        curr_open_tickets = {int(p["ticket"]) for p in live_open}
        curr_pending_tickets = {int(o["ticket"]) for o in live_pendings}
        c_px = float(last_setup.get("current_price") or 0.0)
        curr_atr = float(last_setup.get("current_atr") or 3.0)
        live_rng = float(last_setup.get("live_bar_range") or 0.0)

        if start_price is None and c_px > 0:
            start_price = c_px
            init_m5_bar_time = bars_5m[-1].open_time if bars_5m else None
            init_live_rng = live_rng

        if log_progress:
            now_bkk = datetime.now(TZ_BANGKOK).strftime("%H:%M:%S")
            c_sp = float(last_setup.get("spread") or 0.0)
            pend_txt = (
                ",".join(f"#{o['ticket']}@{float(o.get('price', 0)):.2f}" for o in live_pendings)
                if live_pendings
                else "0"
            )
            print(
                f"[AI-Radar {now_bkk}] Price ${c_px:.2f} | Spread ${c_sp:.2f} | "
                f"Open: {len(curr_open_tickets)} | Pending: {pend_txt}",
                file=sys.stderr,
                flush=True,
            )

        # Wake Condition A: Open position closed (TP / SL / BE)
        closed_tickets = init_open_tickets - curr_open_tickets
        if closed_tickets:
            wake_reason = "POSITION_CLOSED"
            wake_detail = f"ไม้ที่ถืออยู่ถูกปิดแล้ว (Ticket: {sorted(closed_tickets)})"
            try:
                from src.analysis.trade_reviewer import sync_and_review_all
                journal_sync_res = sync_and_review_all()
            except Exception as exc:
                journal_sync_res = {"warning": str(exc)}
            break

        # Wake Condition B: Pending Limit filled into live open position
        newly_opened = curr_open_tickets - init_open_tickets
        if newly_opened:
            wake_reason = "LIMIT_ORDER_FILLED"
            wake_detail = f"Pending Limit ถูกเกี่ยวเปิดเป็นสถานะจริงแล้ว (Ticket: {sorted(newly_opened)})"
            break

        # Wake Condition C: Watchdog had to emergency-cancel AI's Pending Limit
        if lim_guard.get("cancelled"):
            wake_reason = "LIMIT_EMERGENCY_CANCELLED"
            wake_detail = "; ".join(lim_guard["actions"])
            break

        # Also update tracked pending if expired naturally on broker
        if init_pending_tickets and not curr_pending_tickets and not curr_open_tickets:
            wake_reason = "LIMIT_EXPIRED_ON_BROKER"
            wake_detail = f"คำสั่ง Pending Limit หมดอายุ TTL บนโบรกเกอร์แล้ว ({sorted(init_pending_tickets)})"
            break

        # Wake Condition C2: Pre-Fill AI Inspection when price approaches AI's Pending Limit
        if live_pendings and not curr_open_tickets:
            approach = _check_pending_limit_approach(
                live_pendings,
                last_setup,
                limit_approach_atr=limit_approach_atr,
                guard_ticket=guard_ticket,
            )
            if approach:
                wake_reason = "LIMIT_APPROACHING"
                wake_detail = approach["detail"]
                planned_trade_overlay = {
                    "entry": approach["price"],
                    "sl": approach["sl"],
                    "tp": approach["tp"],
                }
                break

        in_news, _ = is_news_blackout()
        in_roll, _ = is_rollover_blackout()

        # Wake Condition D: M15/H1 Zone Proximity (flat OR opposite-side zone while holding a distant limit)
        if not sniper_m5 and not curr_open_tickets and not in_news and not in_roll:
            prox_msg = _check_zone_proximity(
                last_setup,
                proximity_atr=proximity_atr,
                pending_orders=live_pendings,
            )
            if prox_msg:
                wake_reason = "ZONE_PROXIMITY"
                wake_detail = prox_msg
                break

            # Wake Condition D2: Fresh M5 Sub-Structure Zone Proximity inside wide M15/H1 ranges
            if bars_5m:
                m5_prox_msg = _check_m5_zone_proximity(
                    bars_5m,
                    last_setup,
                    pending_orders=live_pendings,
                )
                if m5_prox_msg:
                    wake_reason = "M5_ZONE_PROXIMITY"
                    wake_detail = m5_prox_msg
                    break

            # Wake Condition D3: Market Momentum / Price Displacement Alert when flat (never wakes at iter 0)
            if poll_iter > 0 and curr_atr > 0:
                curr_m5_time = bars_5m[-1].open_time if bars_5m else None
                spike_thresh = 0.95 * curr_atr  # ~1.58x M5_ATR
                new_m5_spike = (
                    live_rng >= spike_thresh
                    and (init_live_rng < spike_thresh or curr_m5_time != init_m5_bar_time)
                )
                if new_m5_spike:
                    momentum_spike_triggered = True
                    wake_reason = "MARKET_MOMENTUM_ALERT"
                    wake_detail = (
                        f"แท่ง M5 กระชากแรงกลางทาง (${live_rng:.2f} >= 1.5x M5_ATR ที่ราคา ${c_px:.2f}) "
                        f"— ปลุก AI เช็กโครงสร้างใหม่ทันที"
                    )
                    break
                if displacement_atr > 0 and start_price and c_px > 0:
                    moved = abs(c_px - start_price)
                    if moved >= (displacement_atr * curr_atr):
                        wake_reason = "MARKET_MOMENTUM_ALERT"
                        wake_detail = (
                            f"ราคาขยับออกจากจุดเริ่มเฝ้า ${moved:.2f} "
                            f"(${start_price:.2f} -> ${c_px:.2f}, >= {displacement_atr:.2f}x ATR) — ปลุก AI อัปเดตแผน"
                        )
                        break

        # Wake Condition E: Abnormal M5 Volatility Spike while holding an open position
        if curr_open_tickets and curr_atr > 0 and live_rng >= (1.6 * curr_atr):
            wake_reason = "OPEN_POSITION_VOLATILITY_ALERT"
            wake_detail = f"กราฟ M5 แกว่งแรง (${live_rng:.2f} >= 1.6x ATR) ขณะถือออเดอร์ ให้ AI ตรวจเช็กทรงกราฟ"
            break

        elapsed = time.monotonic() - start_mono
        if elapsed >= max_wait_sec:
            wake_reason = "SNIPER_M5_BAR_CHECK" if sniper_m5 else "HEARTBEAT_TIMEOUT"
            wake_detail = (
                f"ครบรอบซุ่มเฝ้าปิดแท่ง M5 ({int(elapsed)}s)"
                if sniper_m5
                else f"ครบรอบตรวจสุขภาพพอร์ต/ข่าวด่วนตามกำหนด ({int(elapsed)}s)"
            )
            break

        step_sleep = min(poll_sec, max(0.05, max_wait_sec - elapsed))
        sleep_fn(step_sleep)
        poll_iter += 1
        elapsed = time.monotonic() - start_mono

    if log_progress:
        print(f"[AI-Radar] Wakeup -> {wake_reason}: {wake_detail}", file=sys.stderr, flush=True)

    should_draw_chart = wake_reason in (
        "ZONE_PROXIMITY",
        "M5_ZONE_PROXIMITY",
        "LIMIT_APPROACHING",
        "SNIPER_M5_BAR_CHECK",
        "LIMIT_ORDER_FILLED",
        "OPEN_POSITION_VOLATILITY_ALERT",
    ) or (wake_reason == "MARKET_MOMENTUM_ALERT" and momentum_spike_triggered)
    ctx_builder = context_fn or build_gold_ai_context
    ctx_kwargs: Dict[str, Any] = {
        "include_chart": should_draw_chart,
        "event_tag": wake_reason,
        "note": wake_detail,
        "client": cli,
        "setup_override": last_setup if last_setup else None,
    }
    if planned_trade_overlay:
        ctx_kwargs["planned_trade"] = planned_trade_overlay
    ctx = ctx_builder(**ctx_kwargs)
    return {
        "wakeup_reason": wake_reason,
        "wakeup_detail": wake_detail,
        "waited_seconds": round(elapsed, 1),
        "watchdog_actions": accumulated_actions,
        "journal_sync": journal_sync_res,
        "context": ctx,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="XAU/USD AI Trader Mode Standalone Bridge (Mode 2)")
    parser.add_argument(
        "action",
        choices=["context", "place-market", "place-limit", "modify-sltp", "cancel-limit", "close", "wait-for-trigger"],
    )
    parser.add_argument("--direction", type=str, default="BUY")
    parser.add_argument("--price", type=float, default=0.0, help="Limit entry price")
    parser.add_argument("--sl", type=float, default=0.0, help="Mandatory Hard Stop Loss price")
    parser.add_argument("--tp", type=float, default=0.0, help="Take Profit price")
    parser.add_argument("--ttl", type=int, default=15, help="Pending Limit Dead Man's Switch expiry (minutes)")
    parser.add_argument("--ticket", type=int, default=0)
    parser.add_argument("--chart", action="store_true", default=False, help="Render Base-anchored M15+M5 chart")
    parser.add_argument("--reason", "--note", dest="reason", type=str, default="")
    parser.add_argument("--poll", type=float, default=20.0, help="Radar poll interval in seconds")
    parser.add_argument("--max-wait", type=float, default=900.0, help="Max wait seconds before heartbeat wakeup")
    parser.add_argument("--proximity-atr", type=float, default=0.80, help="ATR multiple proximity threshold to wake AI")
    parser.add_argument("--limit-approach-atr", type=float, default=0.35, help="ATR multiple before Pending Limit to wake AI for pre-fill check")
    parser.add_argument("--displacement-atr", type=float, default=1.0, help="ATR multiple move from start price to wake AI when flat")
    parser.add_argument("--guard-ticket", type=int, default=0, help="Pending ticket already verified by AI on approach")
    parser.add_argument("--sniper-m5", action="store_true", default=False, help="Wait full M5 interval when already at zone")
    parser.add_argument("--sync-next-m5", action="store_true", default=False, help="Wait until exact next M5 candle close while keeping watchdog active")

    args = parser.parse_args()

    if args.action == "context":
        res = build_gold_ai_context(include_chart=args.chart, event_tag="MANUAL_CONTEXT", note=args.reason)
    elif args.action == "place-market":
        res = ai_place_market(direction=args.direction, sl=args.sl, tp=args.tp, reason=args.reason or "AI Market Entry")
    elif args.action == "place-limit":
        res = ai_place_limit(
            direction=args.direction,
            price=args.price,
            sl=args.sl,
            tp=args.tp,
            ttl_minutes=args.ttl,
            reason=args.reason or "AI Limit Entry",
        )
    elif args.action == "modify-sltp":
        res = ai_modify_sltp(ticket=args.ticket, sl=args.sl, tp=args.tp, reason=args.reason or "AI Modify SL/TP")
    elif args.action == "cancel-limit":
        res = ai_cancel_limits(ticket=args.ticket, reason=args.reason or "AI Cancel Limit")
    elif args.action == "close":
        res = ai_close_position(ticket=args.ticket, reason=args.reason or "AI Early Close")
    elif args.action == "wait-for-trigger":
        res = wait_for_trigger(
            poll_sec=args.poll,
            max_wait_sec=args.max_wait,
            proximity_atr=args.proximity_atr,
            limit_approach_atr=args.limit_approach_atr,
            displacement_atr=args.displacement_atr,
            guard_ticket=args.guard_ticket,
            sniper_m5=args.sniper_m5,
            sync_next_m5=args.sync_next_m5,
        )
    else:
        res = {"error": f"Unknown action: {args.action}"}

    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
