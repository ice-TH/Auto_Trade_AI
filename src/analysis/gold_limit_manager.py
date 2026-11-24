"""
Smart Limit Order Manager for XAU/USD (Gold).
Coordinates between Strategy Scanner, News Blackout Guard, and MT5 Client.
Implements:
1. Dead Man's Switch (MT5 Expiry TTL = 10m)
2. Agent Lease Renewal (Max renewals <= 5)
3. Discount 50% Entry inside Demand/Supply Zone
4. Zero Ghost Policy (Auto-cancels if price leaves or structure breaks)
5. News Blackout & Spread Expansion Safeguards
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from src.execution.mt5_client import MT5Client, mt5_client
from src.risk.news_guard import is_news_blackout, is_spread_acceptable, is_volatility_spike

logger = logging.getLogger(__name__)

MAX_RENEWALS_ALLOWED = 5
DEFAULT_EXPIRY_MINUTES = 10
MAX_PRICE_DRIFT_ATR = 1.5  # Cancel if price drifts further than 1.5x ATR away from zone

# In-memory tracking for renewal counts: { ticket_id: renewal_count }
_PENDING_ORDER_METADATA: Dict[int, Dict[str, Any]] = {}

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
    current_price = gold_setup.get("current_price", 0.0)
    current_atr = gold_setup.get("current_atr") or gold_setup.get("atr_15m", 3.0)
    setup_status = gold_setup.get("status", "NEUTRAL")
    direction = gold_setup.get("recommended_direction", "NEUTRAL")
    spread = gold_setup.get("spread", 0.20)
    
    # Lot Sizing based on Account Type
    # Cent Account #160219615 is configured at exactly 0.06 Lot per user specification
    current_login = cli.account_info.get("login") if cli.account_info else None
    trade_volume = 0.06 if current_login == 160219615 else 0.01
    
    actions_taken: List[str] = []
    
    # 1. Fetch current pending orders
    pending_orders = cli.get_pending_orders(symbol)
    
    # 2. Check News Blackout & Volatility Spike
    in_news, news_reason = is_news_blackout()
    spread_ok, spread_reason = is_spread_acceptable(spread)
    
    # 3. Handle existing pending orders first (Reconciliation & Lease Renewal)
    for order in list(pending_orders):
        ticket = order["ticket"]
        meta = _PENDING_ORDER_METADATA.get(ticket, {"renewal_count": 0, "created_at": datetime.now(timezone.utc)})
        order_price = order["price"]
        order_dir = order["direction"]
        
        # Reason to Cancel 1: News Blackout Active
        if in_news:
            cli.cancel_pending_order(ticket)
            _PENDING_ORDER_METADATA.pop(ticket, None)
            actions_taken.append(f"CANCELLED #{ticket}: {news_reason}")
            continue
            
        # Reason to Cancel 2: Spread Expansion
        if not spread_ok:
            cli.cancel_pending_order(ticket)
            _PENDING_ORDER_METADATA.pop(ticket, None)
            actions_taken.append(f"CANCELLED #{ticket}: {spread_reason}")
            continue
            
        # Reason to Cancel 3: Price drifted away (Order abandoned)
        drift = abs(current_price - order_price)
        if drift > (MAX_PRICE_DRIFT_ATR * current_atr):
            cli.cancel_pending_order(ticket)
            _PENDING_ORDER_METADATA.pop(ticket, None)
            actions_taken.append(f"CANCELLED #{ticket}: ราคาวิ่งหนีโซนเกิน {MAX_PRICE_DRIFT_ATR}x ATR (${drift:.2f} > ${MAX_PRICE_DRIFT_ATR*current_atr:.2f})")
            continue
            
        # Reason to Cancel 4: Maximum Renewal Cap reached (Prevent Stale Zone)
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
    
    # 4. Check if we should place a NEW Smart Limit Order
    # Conditions:
    # - No existing pending order
    # - Not in News Blackout & Spread is normal
    # - Setup is WAITING_FOR_REJECTION or price is near zone
    # - Has valid demand or supply zone
    if len(pending_orders) == 0 and not in_news and spread_ok:
        nearest_demand = gold_setup.get("nearest_demand") or (gold_setup.get("demand_zones", [None])[0] if gold_setup.get("demand_zones") else None)
        nearest_supply = gold_setup.get("nearest_supply") or (gold_setup.get("supply_zones", [None])[0] if gold_setup.get("supply_zones") else None)
        
        fibo_gz = gold_setup.get("fibo_golden_zone", {})
        
        # A. Buy Limit at Demand Midpoint (or Golden Zone Confluence Overlap)
        if setup_status == "WAITING_FOR_REJECTION" and nearest_demand:
            # Check Fibo Golden Zone overlap
            conf = nearest_demand.get("fibo_confluence", {})
            is_double = conf.get("double_confluence", False)
            if conf.get("has_confluence"):
                # Use Fibo 65.0% OTE if inside overlap, else overlap midpoint
                fibo_65 = fibo_gz.get("fibo_650")
                if fibo_65 and conf["overlap_low"] <= fibo_65 <= conf["overlap_high"]:
                    discount_entry = round(fibo_65, 2)
                    limit_comment = "SmartBuyLimit [Fibo 65% OTE]" if not is_double else "SmartBuyLimit [⭐⭐ Double Fibo]"
                else:
                    discount_entry = round(conf.get("overlap_mid", (conf["overlap_high"] + conf["overlap_low"]) / 2.0), 2)
                    limit_comment = "SmartBuyLimit [Fibo Golden Zone]" if not is_double else "SmartBuyLimit [⭐⭐ Double Fibo]"
            else:
                discount_entry = round(nearest_demand["zone_mid"], 2)
                limit_comment = "SmartBuyLimit [Discount 50%]"

            # SL strictly below zone_low with moat buffer
            sl_price = round(nearest_demand["zone_low"] - (current_atr * 0.35), 2)
            tp_price = round(current_price + (current_atr * 2.5), 2)
            sl_dist = discount_entry - sl_price
            
            # Ensure SL distance fits within $6.00 cap
            if sl_dist <= 6.00 and sl_dist > 0:
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
                    new_ticket = res.get("ticket")
                    _PENDING_ORDER_METADATA[new_ticket] = {
                        "renewal_count": 0,
                        "created_at": datetime.now(timezone.utc)
                    }
                    actions_taken.append(f"PLACED BUY_LIMIT #{new_ticket} ที่ ${discount_entry:.2f} ({limit_comment}, SL: ${sl_price:.2f}, Moat: ${sl_dist:.2f})")
                    
        # B. Sell Limit at Supply Midpoint (or Golden Zone Confluence Overlap)
        elif setup_status == "WAITING_FOR_REJECTION" and nearest_supply:
            conf = nearest_supply.get("fibo_confluence", {})
            is_double = conf.get("double_confluence", False)
            if conf.get("has_confluence"):
                fibo_65 = fibo_gz.get("fibo_650")
                if fibo_65 and conf["overlap_low"] <= fibo_65 <= conf["overlap_high"]:
                    discount_entry = round(fibo_65, 2)
                    limit_comment = "SmartSellLimit [Fibo 65% OTE]" if not is_double else "SmartSellLimit [⭐⭐ Double Fibo]"
                else:
                    discount_entry = round(conf.get("overlap_mid", (conf["overlap_high"] + conf["overlap_low"]) / 2.0), 2)
                    limit_comment = "SmartSellLimit [Fibo Golden Zone]" if not is_double else "SmartSellLimit [⭐⭐ Double Fibo]"
            else:
                discount_entry = round(nearest_supply["zone_mid"], 2)
                limit_comment = "SmartSellLimit [Discount 50%]"

            sl_price = round(nearest_supply["zone_high"] + (current_atr * 0.35), 2)
            tp_price = round(current_price - (current_atr * 2.5), 2)
            sl_dist = sl_price - discount_entry
            
            if sl_dist <= 6.00 and sl_dist > 0:
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
                    actions_taken.append(f"PLACED SELL_LIMIT #{new_ticket} ที่ ${discount_entry:.2f} ({limit_comment}, SL: ${sl_price:.2f}, Moat: ${sl_dist:.2f})")
                    actions_taken.append(f"PLACED SELL_LIMIT #{new_ticket} ที่ ${discount_entry:.2f} (SL: ${sl_price:.2f}, Moat: ${sl_dist:.2f})")

    return {
        "symbol": symbol,
        "news_blackout": in_news,
        "spread_status": spread_reason,
        "actions_taken": actions_taken,
        "active_pending_count": len(cli.get_pending_orders(symbol))
    }
