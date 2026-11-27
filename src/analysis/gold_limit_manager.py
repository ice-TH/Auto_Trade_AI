"""
Smart Limit Order Manager for XAU/USD (Gold).
Coordinates between Strategy Scanner, News/Rollover/Volatility Guards, and MT5 Client.
Implements:
1. Single-Position Guard (Auto-cancels pending orders and blocks new limits if an XAU position is open)
2. Dead Man's Switch (MT5 Expiry TTL = 10m) & Agent Lease Renewal (Max renewals <= 5)
3. Discount 50% / Fibo 65% OTE Entry inside Demand/Supply Zone (Mutual Exclusion: never places Buy & Sell together)
4. Zero Ghost Policy (Auto-cancels on News, Rollover, Spread expansion, Volatility Spike, Falling Knife, Structure break, or Drift)
5. Consistent Structural SL Moat (0.75x ATR + Live Spread on SELL, strictly <= MAX_GOLD_SL_USD = $8.00)
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from src.execution.mt5_client import MT5Client, mt5_client
from src.risk.news_guard import (
    is_news_blackout,
    is_rollover_blackout,
    is_spread_acceptable,
    is_volatility_spike,
)
from src.analysis.gold_strategy import (
    MAX_GOLD_SL_USD,
    MIN_GOLD_RR_RATIO,
    MIN_HEADROOM_ATR_MULT,
    check_fibo_confluence,
)

logger = logging.getLogger(__name__)

MAX_RENEWALS_ALLOWED = 5
DEFAULT_EXPIRY_MINUTES = 10
MAX_PRICE_DRIFT_ATR = 1.5  # Cancel if price drifts further than 1.5x ATR away from pending order

# In-memory tracking for renewal counts: { ticket_id: renewal_count }
_PENDING_ORDER_METADATA: Dict[int, Dict[str, Any]] = {}


def _get_open_gold_positions(cli: MT5Client) -> List[Dict[str, Any]]:
    """Return currently open positions on Gold (XAU / GOLD) for Single-Position Guard enforcement."""
    positions = cli.get_open_positions() or []
    return [
        p for p in positions
        if any(k in str(p.get("symbol", "")).upper() for k in ("XAU", "GOLD"))
    ]


def _zone_passes_fibo_or_h1_rr_gate(zone: Dict[str, Any], fibo_obj: Optional[Dict[str, Any]]) -> bool:
    """
    Require at least Fibo 38.2%-78.6% confluence (GOLDEN_ZONE or TREND_PULLBACK)
    or an H1/Daily Role Reversal before placing a Smart Limit order.
    If neither `fibo_confluence` nor `fibo_obj` is provided at all (minimal synthetic mock), allow legacy fallback.
    """
    if zone.get("is_h1_role_reversal"):
        return True
    conf = zone.get("fibo_confluence")
    if isinstance(conf, dict) and len(conf) > 0:
        return bool(conf.get("has_ok_fibo") or conf.get("has_confluence"))
    if isinstance(fibo_obj, dict) and "golden_zone_high" in fibo_obj:
        eval_c = check_fibo_confluence(float(zone["zone_high"]), float(zone["zone_low"]), fibo_obj)
        return bool(eval_c.get("has_ok_fibo") or eval_c.get("has_confluence"))
    return True


def manage_gold_limits(
    gold_setup: Dict[str, Any],
    client: Optional[MT5Client] = None
) -> Dict[str, Any]:
    """
    Main reconciliation loop for Gold Pending Orders.
    Called every minute or scanner cycle.
    """
    cli = client or mt5_client
    symbol = gold_setup.get("mt5_symbol") or gold_setup.get("symbol", "XAUUSD")
    current_price = float(gold_setup.get("current_price", 0.0))
    current_atr = float(gold_setup.get("current_atr") or gold_setup.get("atr_15m", 3.0))
    live_bar_range = float(gold_setup.get("live_bar_range", 0.0))
    setup_status = gold_setup.get("status", "NEUTRAL")
    direction = gold_setup.get("recommended_direction", "NEUTRAL")
    spread = float(gold_setup.get("spread", 0.20))

    # Lot Sizing based on Account Type
    # Cent Account #160219615 is configured at exactly 0.06 Lot per user specification
    current_login = cli.account_info.get("login") if cli.account_info else None
    trade_volume = 0.06 if current_login == 160219615 else 0.01

    actions_taken: List[str] = []

    # 1. Fetch current open positions & pending orders
    open_gold_positions = _get_open_gold_positions(cli)
    has_open_position = len(open_gold_positions) > 0
    pending_orders = cli.get_pending_orders(symbol)

    # 2. Check News Blackout, Rollover Close, Spread & Volatility Spike
    in_news, news_reason = is_news_blackout()
    in_rollover, rollover_reason = is_rollover_blackout()
    spread_ok, spread_reason = is_spread_acceptable(spread)
    in_vol_spike, vol_reason = is_volatility_spike(live_bar_range, current_atr, spike_multiplier=2.2)

    nearest_demand = gold_setup.get("nearest_demand") or (gold_setup.get("demand_zones", [None])[0] if gold_setup.get("demand_zones") else None)
    nearest_supply = gold_setup.get("nearest_supply") or (gold_setup.get("supply_zones", [None])[0] if gold_setup.get("supply_zones") else None)

    # 3. Handle existing pending orders first (Reconciliation, Safety & Lease Renewal)
    for order in list(pending_orders):
        ticket = order["ticket"]
        meta = _PENDING_ORDER_METADATA.get(ticket, {"renewal_count": 0, "created_at": datetime.now(timezone.utc)})
        order_price = float(order["price"])
        order_dir = order["direction"]
        order_sl = float(order.get("sl") or order.get("sl_price", 0.0))

        # Reason to Cancel 0: Single-Position Guard (Position already open!)
        if has_open_position:
            cli.cancel_pending_order(ticket)
            _PENDING_ORDER_METADATA.pop(ticket, None)
            actions_taken.append(f"CANCELLED #{ticket}: มีสถานะทองคำเปิดอยู่แล้ว ({len(open_gold_positions)} ไม้) ยกเลิก Pending ซ้อนทับ [Single-Position Guard]")
            continue

        # Reason to Cancel 1: News Blackout Active
        if in_news:
            cli.cancel_pending_order(ticket)
            _PENDING_ORDER_METADATA.pop(ticket, None)
            actions_taken.append(f"CANCELLED #{ticket}: {news_reason}")
            continue

        # Reason to Cancel 1B: Daily Rollover / Market Close Window
        if in_rollover:
            cli.cancel_pending_order(ticket)
            _PENDING_ORDER_METADATA.pop(ticket, None)
            actions_taken.append(f"CANCELLED #{ticket}: {rollover_reason}")
            continue

        # Reason to Cancel 2: Spread Expansion
        if not spread_ok:
            cli.cancel_pending_order(ticket)
            _PENDING_ORDER_METADATA.pop(ticket, None)
            actions_taken.append(f"CANCELLED #{ticket}: {spread_reason}")
            continue

        # Reason to Cancel 2B: Abnormal Volatility Spike
        if in_vol_spike:
            cli.cancel_pending_order(ticket)
            _PENDING_ORDER_METADATA.pop(ticket, None)
            actions_taken.append(f"CANCELLED #{ticket}: {vol_reason}")
            continue

        # Reason to Cancel 3: Violent Candle (Falling Knife on BUY or Rocket Surge on SELL)
        if order_dir == "BUY" and setup_status == "REJECTED_FALLING_KNIFE":
            cli.cancel_pending_order(ticket)
            _PENDING_ORDER_METADATA.pop(ticket, None)
            actions_taken.append(f"CANCELLED #{ticket}: ตรวจพบแท่งเทียนทิ้งตัวรุนแรง (Falling Knife) ยกเลิก Buy Limit เพื่อป้องกันความเสียหาย")
            continue
        if order_dir == "SELL" and setup_status == "REJECTED_ROCKET_SURGE":
            cli.cancel_pending_order(ticket)
            _PENDING_ORDER_METADATA.pop(ticket, None)
            actions_taken.append(f"CANCELLED #{ticket}: ตรวจพบแท่งเทียนพุ่งตัวรุนแรง (Rocket Surge) ยกเลิก Sell Limit เพื่อป้องกันความเสียหาย")
            continue

        # Reason to Cancel 4: Structural Invalidation (Price broke past SL / Zone floor/ceiling)
        if order_dir == "BUY":
            demand_floor = nearest_demand["zone_low"] if nearest_demand else (order_price - 5.0)
            if current_price < (demand_floor - (current_atr * 0.50)) or (order_sl > 0 and current_price <= order_sl):
                cli.cancel_pending_order(ticket)
                _PENDING_ORDER_METADATA.pop(ticket, None)
                actions_taken.append(f"CANCELLED #{ticket}: โครงสร้าง Demand ถูกทำลาย (ราคา ${current_price:.2f} ทะลุแนวรับ ${demand_floor:.2f})")
                continue
        elif order_dir == "SELL":
            supply_ceiling = nearest_supply["zone_high"] if nearest_supply else (order_price + 5.0)
            if current_price > (supply_ceiling + (current_atr * 0.50)) or (order_sl > 0 and current_price >= order_sl):
                cli.cancel_pending_order(ticket)
                _PENDING_ORDER_METADATA.pop(ticket, None)
                actions_taken.append(f"CANCELLED #{ticket}: โครงสร้าง Supply ถูกทำลาย (ราคา ${current_price:.2f} ทะลุแนวต้าน ${supply_ceiling:.2f})")
                continue

        # Reason to Cancel 5: Price drifted away (Order abandoned)
        drift = abs(current_price - order_price)
        if drift > (MAX_PRICE_DRIFT_ATR * current_atr):
            cli.cancel_pending_order(ticket)
            _PENDING_ORDER_METADATA.pop(ticket, None)
            actions_taken.append(f"CANCELLED #{ticket}: ราคาวิ่งหนีโซนเกิน {MAX_PRICE_DRIFT_ATR}x ATR (${drift:.2f} > ${MAX_PRICE_DRIFT_ATR*current_atr:.2f})")
            continue

        # Reason to Cancel 6: Maximum Renewal Cap reached (Prevent Stale Zone)
        if meta["renewal_count"] >= MAX_RENEWALS_ALLOWED:
            cli.cancel_pending_order(ticket)
            _PENDING_ORDER_METADATA.pop(ticket, None)
            actions_taken.append(f"CANCELLED #{ticket}: ครบกำหนดการต่อเวลาสูงสุด ({MAX_RENEWALS_ALLOWED} รอบ) ยกเลิกเพื่อสแกนโซนใหม่")
            continue

        # If still in valid zone and structure is intact -> RENEW LEASE (Dead Man's Switch extension)
        renew_res = cli.renew_pending_order_expiry(ticket, additional_minutes=DEFAULT_EXPIRY_MINUTES)
        if renew_res.get("success"):
            meta["renewal_count"] += 1
            _PENDING_ORDER_METADATA[ticket] = meta
            actions_taken.append(f"RENEWED #{ticket}: ต่อเวลาสำเร็จ (รอบที่ {meta['renewal_count']}/{MAX_RENEWALS_ALLOWED})")

    # Refresh pending list
    pending_orders = cli.get_pending_orders(symbol)

    # Reject statuses that explicitly prohibit any limit fallback
    hard_blocked_statuses = {
        "REJECTED_FALLING_KNIFE",
        "REJECTED_ROCKET_SURGE",
        "REJECTED_NEAR_RESISTANCE",
        "REJECTED_NEAR_SUPPORT_HEADROOM",
    }

    # 4. Place a NEW Smart Limit Order ONLY if:
    # - Zero open Gold positions (Single-Position Guard)
    # - Zero existing pending orders
    # - Safe from News, Rollover, Spread expansion, Volatility Spike, and Hard Rejection Guards
    placed_in_this_cycle = False

    if (
        not has_open_position
        and len(pending_orders) == 0
        and not in_news
        and not in_rollover
        and spread_ok
        and not in_vol_spike
        and setup_status not in hard_blocked_statuses
    ):
        fibo_buy = gold_setup.get("fibo_buy") or gold_setup.get("fibo_golden_zone", {})
        fibo_sell = gold_setup.get("fibo_sell") or gold_setup.get("fibo_golden_zone", {})
        rec_entry = gold_setup.get("recommended_entry")
        rec_sl = gold_setup.get("recommended_sl")
        rec_tp = gold_setup.get("recommended_tp")

        # Determine closer zone when status is WAITING_FOR_REJECTION (prevents placing both Buy & Sell)
        dist_to_demand = abs(current_price - nearest_demand["zone_high"]) if nearest_demand else 99999.0
        dist_to_supply = abs(current_price - nearest_supply["zone_low"]) if nearest_supply else 99999.0

        # A. Buy Limit Evaluation
        can_place_buy = (
            setup_status == "ACTIONABLE_BUY_LIMIT"
            or (
                setup_status == "WAITING_FOR_REJECTION"
                and nearest_demand is not None
                and direction in ("BUY", "NEUTRAL")
                and dist_to_demand <= dist_to_supply
                and dist_to_demand <= (current_atr * 0.50)
            )
        )
        if can_place_buy and nearest_demand:
            if not _zone_passes_fibo_or_h1_rr_gate(nearest_demand, fibo_buy):
                actions_taken.append(
                    f"SKIPPED_NO_FIBO_CONFLUENCE: โซน Demand (${nearest_demand['zone_low']:.2f}-${nearest_demand['zone_high']:.2f}) "
                    f"ไม่มีแนว Fibo 38.2%-78.6% หรือ H1 Role Reversal รองรับ"
                )
                can_place_buy = False
        if can_place_buy and nearest_demand:
            if setup_status == "ACTIONABLE_BUY_LIMIT" and rec_entry and rec_sl and rec_tp:
                discount_entry = float(rec_entry)
                sl_price = float(rec_sl)
                tp_price = float(rec_tp)
                conf = nearest_demand.get("fibo_confluence", {})
                is_double = conf.get("double_confluence", False)
                tier = conf.get("fibo_tier", "GOLDEN_ZONE")
                if is_double:
                    limit_comment = "SmartBuyLimit [⭐⭐ Double Fibo]"
                elif tier == "TREND_PULLBACK":
                    limit_comment = "SmartBuyLimit [Fibo 38.2-50%]"
                elif nearest_demand.get("is_h1_role_reversal"):
                    limit_comment = "SmartBuyLimit [H1 Role Reversal]"
                else:
                    limit_comment = "SmartBuyLimit [Fibo 65% OTE]"
            else:
                conf = nearest_demand.get("fibo_confluence", {})
                is_double = conf.get("double_confluence", False)
                if conf.get("has_confluence"):
                    fibo_65 = conf.get("fibo_650") or fibo_buy.get("fibo_650")
                    if fibo_65 and conf.get("overlap_low", 0) <= fibo_65 <= conf.get("overlap_high", 99999):
                        discount_entry = round(float(fibo_65), 2)
                        limit_comment = "SmartBuyLimit [⭐⭐ Double Fibo]" if is_double else "SmartBuyLimit [Fibo 65% OTE]"
                    else:
                        discount_entry = round(conf.get("overlap_mid", (nearest_demand["zone_high"] + nearest_demand["zone_low"]) / 2.0), 2)
                        limit_comment = "SmartBuyLimit [⭐⭐ Double Fibo]" if is_double else "SmartBuyLimit [Fibo Golden Zone]"
                elif conf.get("has_ok_fibo"):
                    target_lv = conf.get("fibo_target_level") or conf.get("overlap_mid")
                    z_mid = (nearest_demand["zone_high"] + nearest_demand["zone_low"]) / 2.0
                    raw_cand = float(target_lv) if target_lv is not None else z_mid
                    discount_entry = round(min(max(raw_cand, nearest_demand["zone_low"]), nearest_demand["zone_high"]), 2)
                    limit_comment = "SmartBuyLimit [Fibo 38.2-50%]"
                else:
                    discount_entry = round(nearest_demand.get("zone_mid", (nearest_demand["zone_high"] + nearest_demand["zone_low"]) / 2.0), 2)
                    limit_comment = "SmartBuyLimit [H1 Role Reversal]" if nearest_demand.get("is_h1_role_reversal") else "SmartBuyLimit [Discount 50%]"

                # Consistent structural moat buffer (0.75x ATR, fallback to 0.50x ATR only if zone is tight, never artificially shrunk below 0.50x)
                sl_price = round(nearest_demand["zone_low"] - (current_atr * 0.75), 2)
                sl_dist = discount_entry - sl_price

                target_tp = round(discount_entry + (sl_dist * 2.0), 2)
                if nearest_supply and nearest_supply["zone_low"] > discount_entry:
                    target_tp = min(target_tp, round(nearest_supply["zone_low"] - (current_atr * 0.35), 2))
                tp_price = target_tp

            # Check overhead headroom from limit entry
            buy_headroom = (nearest_supply["zone_low"] - discount_entry) if (nearest_supply and nearest_supply["zone_low"] > discount_entry) else 999.0
            sl_dist = discount_entry - sl_price
            rew_dist = tp_price - discount_entry
            rr = (rew_dist / sl_dist) if sl_dist > 0 else 0.0

            if (
                0 < sl_dist <= MAX_GOLD_SL_USD
                and rr >= MIN_GOLD_RR_RATIO
                and discount_entry < current_price
                and buy_headroom >= (current_atr * 1.0)
            ):
                res = cli.send_limit_order(
                    symbol=symbol,
                    direction="BUY",
                    volume=trade_volume,
                    price=discount_entry,
                    sl_price=sl_price,
                    tp_price=tp_price,
                    expiry_minutes=DEFAULT_EXPIRY_MINUTES,
                    comment=limit_comment
                )
                if res.get("success"):
                    placed_in_this_cycle = True
                    new_ticket = res.get("ticket")
                    _PENDING_ORDER_METADATA[new_ticket] = {
                        "renewal_count": 0,
                        "created_at": datetime.now(timezone.utc)
                    }
                    actions_taken.append(f"PLACED BUY_LIMIT #{new_ticket} ที่ ${discount_entry:.2f} ({limit_comment}, SL: ${sl_price:.2f}, Moat: ${sl_dist:.2f}, R:R: {rr:.2f})")

        # B. Sell Limit Evaluation (Mutually exclusive with Buy Limit!)
        can_place_sell = (
            not placed_in_this_cycle
            and (
                setup_status == "ACTIONABLE_SELL_LIMIT"
                or (
                    setup_status == "WAITING_FOR_REJECTION"
                    and nearest_supply is not None
                    and direction in ("SELL", "NEUTRAL")
                    and dist_to_supply < dist_to_demand
                    and dist_to_supply <= (current_atr * 0.50)
                )
            )
        )
        if can_place_sell and nearest_supply:
            if not _zone_passes_fibo_or_h1_rr_gate(nearest_supply, fibo_sell):
                actions_taken.append(
                    f"SKIPPED_NO_FIBO_CONFLUENCE: โซน Supply (${nearest_supply['zone_low']:.2f}-${nearest_supply['zone_high']:.2f}) "
                    f"ไม่มีแนว Fibo 38.2%-78.6% หรือ H1 Role Reversal รองรับ"
                )
                can_place_sell = False
        if can_place_sell and nearest_supply:
            if setup_status == "ACTIONABLE_SELL_LIMIT" and rec_entry and rec_sl and rec_tp:
                discount_entry = float(rec_entry)
                sl_price = float(rec_sl)
                tp_price = float(rec_tp)
                conf = nearest_supply.get("fibo_confluence", {})
                is_double = conf.get("double_confluence", False)
                tier = conf.get("fibo_tier", "GOLDEN_ZONE")
                if is_double:
                    limit_comment = "SmartSellLimit [⭐⭐ Double Fibo]"
                elif tier == "TREND_PULLBACK":
                    limit_comment = "SmartSellLimit [Fibo 38.2-50%]"
                elif nearest_supply.get("is_h1_role_reversal"):
                    limit_comment = "SmartSellLimit [H1 Role Reversal]"
                else:
                    limit_comment = "SmartSellLimit [Fibo 65% OTE]"
            else:
                conf = nearest_supply.get("fibo_confluence", {})
                is_double = conf.get("double_confluence", False)
                if conf.get("has_confluence"):
                    fibo_65 = conf.get("fibo_650") or fibo_sell.get("fibo_650")
                    if fibo_65 and conf.get("overlap_low", 0) <= fibo_65 <= conf.get("overlap_high", 99999):
                        discount_entry = round(float(fibo_65), 2)
                        limit_comment = "SmartSellLimit [⭐⭐ Double Fibo]" if is_double else "SmartSellLimit [Fibo 65% OTE]"
                    else:
                        discount_entry = round(conf.get("overlap_mid", (nearest_supply["zone_high"] + nearest_supply["zone_low"]) / 2.0), 2)
                        limit_comment = "SmartSellLimit [⭐⭐ Double Fibo]" if is_double else "SmartSellLimit [Fibo Golden Zone]"
                elif conf.get("has_ok_fibo"):
                    target_lv = conf.get("fibo_target_level") or conf.get("overlap_mid")
                    z_mid = (nearest_supply["zone_high"] + nearest_supply["zone_low"]) / 2.0
                    raw_cand = float(target_lv) if target_lv is not None else z_mid
                    discount_entry = round(min(max(raw_cand, nearest_supply["zone_low"]), nearest_supply["zone_high"]), 2)
                    limit_comment = "SmartSellLimit [Fibo 38.2-50%]"
                else:
                    discount_entry = round(nearest_supply.get("zone_mid", (nearest_supply["zone_high"] + nearest_supply["zone_low"]) / 2.0), 2)
                    limit_comment = "SmartSellLimit [H1 Role Reversal]" if nearest_supply.get("is_h1_role_reversal") else "SmartSellLimit [Discount 50%]"

                # Consistent structural moat buffer + live_spread on SELL SL (since SELL closes at Ask)
                sl_price = round(nearest_supply["zone_high"] + (current_atr * 0.75) + max(spread, 0.0), 2)
                sl_dist = sl_price - discount_entry

                target_tp = round(discount_entry - (sl_dist * 2.0), 2)
                if nearest_demand and nearest_demand["zone_high"] < discount_entry:
                    target_tp = max(target_tp, round(nearest_demand["zone_high"] + (current_atr * 0.35), 2))
                tp_price = target_tp

            sell_headroom = (discount_entry - nearest_demand["zone_high"]) if (nearest_demand and nearest_demand["zone_high"] < discount_entry) else 999.0
            sl_dist = sl_price - discount_entry
            rew_dist = discount_entry - tp_price
            rr = (rew_dist / sl_dist) if sl_dist > 0 else 0.0

            if (
                0 < sl_dist <= MAX_GOLD_SL_USD
                and rr >= MIN_GOLD_RR_RATIO
                and discount_entry > current_price
                and sell_headroom >= (current_atr * MIN_HEADROOM_ATR_MULT)
            ):
                res = cli.send_limit_order(
                    symbol=symbol,
                    direction="SELL",
                    volume=trade_volume,
                    price=discount_entry,
                    sl_price=sl_price,
                    tp_price=tp_price,
                    expiry_minutes=DEFAULT_EXPIRY_MINUTES,
                    comment=limit_comment
                )
                if res.get("success"):
                    new_ticket = res.get("ticket")
                    _PENDING_ORDER_METADATA[new_ticket] = {
                        "renewal_count": 0,
                        "created_at": datetime.now(timezone.utc)
                    }
                    actions_taken.append(f"PLACED SELL_LIMIT #{new_ticket} ที่ ${discount_entry:.2f} ({limit_comment}, SL: ${sl_price:.2f}, Moat: ${sl_dist:.2f}, R:R: {rr:.2f})")

    return {
        "symbol": symbol,
        "news_blackout": in_news,
        "rollover_blackout": in_rollover,
        "volatility_spike": in_vol_spike,
        "has_open_position": has_open_position,
        "spread_status": spread_reason,
        "actions_taken": actions_taken,
        "active_pending_count": len(cli.get_pending_orders(symbol))
    }
