"""
Deterministic, Zero-Look-Ahead Historical Backtester for XAU/USD (Gold) Limit-First Strategy.
Compares:
  1) BASELINE (Legacy): Allows placing Limit orders on shallow Demand/Supply zones without Fibo 38.2%-78.6% support.
  2) FIBO_FILTERED (New): Requires at least Fibo 38.2%-78.6% (Golden Zone 61.8%-78.6% or Trend Pullback 38.2%-61.8%)
     or an H1 Role Reversal zone before placing a Limit order.

Strict Realism Rules:
- Zero Look-Ahead: At bar t, only bars with close_time <= bar_t.close_time are visible.
- Realistic Bid/Ask Spread ($0.20 default):
    * BUY Limit fills when Ask <= entry (low + spread <= entry); SL hits on Bid <= sl; TP hits on Bid >= tp.
    * SELL Limit fills when Bid >= entry (high >= entry); SL hits on Ask >= sl (high + spread >= sl); TP hits on Ask <= tp (low + spread <= tp).
- Intra-bar M5 resolution when M5 bars are available; conservative SL-first tie-breaker if both SL & TP touch in the same bar.
- Auto Break-Even +1.0R Guard (+0.30 USD lock) & Knife Guard (cancels pending limit if violent marubozu slams into zone).
- Hard Risk Gate: SL <= $8.00, R:R >= 1.50, Single-Position & Single-Pending-Order exclusivity.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from src.data.base import Bar, DataStatus, SessionType, TimeFrame
from src.data.mt5_adapter import MT5DataAdapter
from src.analysis.indicators import calculate_atr, calculate_ema, calculate_sma
from src.analysis.zones import build_sr_zones
from src.analysis.gold_strategy import (
    MAX_GOLD_SL_USD,
    MIN_GOLD_RR_RATIO,
    MIN_HEADROOM_ATR_MULT,
    MAX_ZONE_RETESTS,
    calculate_fibonacci_retracement,
    check_fibo_confluence,
    combine_overlapping_zones,
    detect_demand_supply_zones,
    detect_zigzag_pivots,
)
from src.analysis.gold_ai_context import (
    _evaluate_zone_limit_candidate,
    _select_fibo_prioritized_zone_candidate,
    _zone_has_golden_confluence,
)

TZ_BKK = ZoneInfo("Asia/Bangkok")


@dataclass
class GoldBacktestTrade:
    mode: str
    direction: str
    entry_tier: str
    fibo_tier: str
    placed_time: str
    entry_time: str
    exit_time: str
    entry_price: float
    initial_sl: float
    final_sl: float
    tp_price: float
    exit_price: float
    risk_usd_per_oz: float
    pnl_usd_per_oz: float
    pnl_account_ccy: float
    r_multiple: float
    exit_reason: str  # TP, SL, BE_SL, END_OF_DATA


def fetch_mt5_gold_bars(bars_15m_count: int = 1500) -> Tuple[str, float, str, Dict[str, List[Bar]]]:
    """
    Fetch historical M5, M15, and H1 bars directly from MetaTrader 5 for XAUUSD / XAUUSDc.
    Returns (resolved_symbol, contract_size, account_currency, {"M5": ..., "M15": ..., "H1": ...}).
    """
    import MetaTrader5 as mt5

    adapter = MT5DataAdapter()
    if not adapter._ensure_connected():
        raise RuntimeError("MT5 is not connected. Please open MetaTrader 5 terminal to run real backtest.")

    sym = adapter._resolve_symbol("XAUUSD") or "XAUUSDc"
    sym_info = mt5.symbol_info(sym)
    acc_info = mt5.account_info()
    contract_size = float(sym_info.trade_contract_size) if sym_info else 100.0
    acc_ccy = str(acc_info.currency) if acc_info else "USC"

    def _pull(tf_mt5: int, tf_enum: TimeFrame, count: int) -> List[Bar]:
        rates = mt5.copy_rates_from_pos(sym, tf_mt5, 0, count)
        if rates is None or len(rates) == 0:
            return []
        step_sec = 300 if tf_enum == TimeFrame.M5 else (900 if tf_enum == TimeFrame.M15 else 3600)
        out: List[Bar] = []
        for idx, r in enumerate(rates):
            ot = datetime.fromtimestamp(int(r["time"]), tz=timezone.utc)
            ct = datetime.fromtimestamp(int(r["time"]) + step_sec, tz=timezone.utc)
            out.append(
                Bar(
                    symbol=sym,
                    timeframe=tf_enum,
                    open_time=ot,
                    close_time=ct,
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=float(r["tick_volume"]),
                    is_confirmed=(idx < len(rates) - 1),
                    status=DataStatus.HISTORICAL,
                    session=SessionType.REGULAR,
                )
            )
        return out

    m15 = _pull(mt5.TIMEFRAME_M15, TimeFrame.M15, bars_15m_count)
    h1_count = max(300, (bars_15m_count // 4) + 120)
    m5_count = min(bars_15m_count * 3 + 100, 10000)
    h1 = _pull(mt5.TIMEFRAME_H1, TimeFrame.H1, h1_count)
    m5 = _pull(mt5.TIMEFRAME_M5, TimeFrame.M5, m5_count)

    return sym, contract_size, acc_ccy, {"M5": m5, "M15": m15, "H1": h1}


def _build_snapshot_structure(
    hist_15m: List[Bar],
    hist_h1: List[Bar],
) -> Dict[str, Any]:
    """Compute zero-look-ahead Demand/Supply, Fibo, Role Reversals, Trend & ATR at a historical bar."""
    curr_price = hist_15m[-1].close
    atr_list = calculate_atr(hist_15m, 14)
    current_atr = max(float(atr_list[-1]["value"]), 1.5) if atr_list else 3.5

    ema15_l = calculate_ema(hist_15m, 15) if len(hist_15m) >= 15 else []
    ma50_l = calculate_sma(hist_15m, 50) if len(hist_15m) >= 50 else []
    h1_ema50_l = calculate_ema(hist_h1, 50) if len(hist_h1) >= 50 else []

    ema15_v = ema15_l[-1]["value"] if ema15_l else None
    ma50_v = ma50_l[-1]["value"] if ma50_l else None
    h1_ema50_v = h1_ema50_l[-1]["value"] if h1_ema50_l else None

    m15_trend = "BULLISH" if (ema15_v and ma50_v and ema15_v > ma50_v) else ("BEARISH" if (ema15_v and ma50_v and ema15_v < ma50_v) else "NEUTRAL")
    h1_trend = "BULLISH" if (h1_ema50_v and curr_price > h1_ema50_v + current_atr * 0.5) else ("BEARISH" if (h1_ema50_v and curr_price < h1_ema50_v - current_atr * 0.5) else "NEUTRAL")
    strong_bull = (h1_trend == "BULLISH" and m15_trend == "BULLISH")
    strong_bear = (h1_trend == "BEARISH" and m15_trend == "BEARISH")

    sr_15m = build_sr_zones("XAUUSD", hist_15m, n_fractal=4, atr_multiplier=0.4)
    h1_sr = build_sr_zones("XAUUSD", hist_h1, n_fractal=3, atr_multiplier=0.4) if len(hist_h1) >= 20 else []
    h1_rr = [z for z in h1_sr if z.is_role_reversed and z.is_active]

    m15_supports = [
        {
            "type": "DEMAND",
            "pattern": "M15_SUPPORT",
            "timeframe": "15m",
            "label": "M15 Support",
            "zone_high": round(z.price_high, 2),
            "zone_low": round(z.price_low, 2),
            "zone_mid": round(z.price_mid, 2),
            "is_broken": z.is_broken,
            "retest_count": z.touch_count,
            "confluence": 1,
        }
        for z in sr_15m if z.zone_type == "SUPPORT" and not z.is_broken and z.is_active and z.touch_count <= MAX_ZONE_RETESTS
    ]
    m15_resistances = [
        {
            "type": "SUPPLY",
            "pattern": "M15_RESISTANCE",
            "timeframe": "15m",
            "label": "M15 Resistance",
            "zone_high": round(z.price_high, 2),
            "zone_low": round(z.price_low, 2),
            "zone_mid": round(z.price_mid, 2),
            "is_broken": z.is_broken,
            "retest_count": z.touch_count,
            "confluence": 1,
        }
        for z in sr_15m if z.zone_type == "RESISTANCE" and not z.is_broken and z.is_active and z.touch_count <= MAX_ZONE_RETESTS
    ]

    ds_15 = detect_demand_supply_zones(hist_15m, min_bars=15, timeframe_label="15m", atr_val=current_atr)
    ds_h1 = detect_demand_supply_zones(hist_h1, min_bars=15, timeframe_label="1H", atr_val=current_atr * 2.0) if len(hist_h1) >= 15 else {"demand_zones": [], "supply_zones": []}

    demands = sorted(
        combine_overlapping_zones(ds_15["demand_zones"] + ds_h1["demand_zones"] + m15_supports, current_atr),
        key=lambda d: abs(curr_price - d["zone_high"]),
    )
    supplies = sorted(
        combine_overlapping_zones(ds_15["supply_zones"] + ds_h1["supply_zones"] + m15_resistances, current_atr),
        key=lambda s: abs(curr_price - s["zone_low"]),
    )

    zz = detect_zigzag_pivots(hist_15m, pivot_legs=8, min_deviation_pct=0.8) if len(hist_15m) >= 20 else []
    if len(zz) < 2 and len(hist_15m) >= 15:
        zz = detect_zigzag_pivots(hist_15m, pivot_legs=5, min_deviation_pct=0.5)

    major_fibo_up: Dict[str, Any] = {}
    minor_fibo_up: Dict[str, Any] = {}
    major_fibo_down: Dict[str, Any] = {}
    minor_fibo_down: Dict[str, Any] = {}

    if len(zz) >= 2:
        last_p, prev_p = zz[-1], zz[-2]
        bars_since = hist_15m[last_p.index:] if last_p.index < len(hist_15m) else []
        if last_p.pivot_type == -1:
            proj_high = max((b.high for b in bars_since), default=last_p.price)
            if (proj_high - last_p.price) >= (current_atr * 2.0):
                minor_fibo_up = calculate_fibonacci_retracement(proj_high, last_p.price, label="Minor", direction="UP")
            if (prev_p.price - last_p.price) >= (current_atr * 2.0):
                minor_fibo_down = calculate_fibonacci_retracement(prev_p.price, last_p.price, label="Minor", direction="DOWN")
        else:
            proj_low = min((b.low for b in bars_since), default=last_p.price)
            if (last_p.price - proj_low) >= (current_atr * 2.0):
                minor_fibo_down = calculate_fibonacci_retracement(last_p.price, proj_low, label="Minor", direction="DOWN")
            if (last_p.price - prev_p.price) >= (current_atr * 2.0):
                minor_fibo_up = calculate_fibonacci_retracement(last_p.price, prev_p.price, label="Minor", direction="UP")

        high_pivs = [p for p in zz if p.pivot_type == 1]
        low_pivs = [p for p in zz if p.pivot_type == -1]
        if high_pivs and low_pivs:
            mh = max(high_pivs, key=lambda p: p.price)
            ml = min(low_pivs, key=lambda p: p.price)
            if (mh.price - ml.price) >= (current_atr * 4.0):
                major_fibo_up = calculate_fibonacci_retracement(mh.price, ml.price, label="Major", direction="UP")
                major_fibo_down = calculate_fibonacci_retracement(mh.price, ml.price, label="Major", direction="DOWN")

    major_fibo_up = major_fibo_up or minor_fibo_up
    major_fibo_down = major_fibo_down or minor_fibo_down
    rr_tol = current_atr * 0.25

    for d in demands:
        maj_c = check_fibo_confluence(d["zone_high"], d["zone_low"], major_fibo_up) if major_fibo_up else {"has_confluence": False, "has_ok_fibo": False, "fibo_tier": "NONE"}
        min_c = check_fibo_confluence(d["zone_high"], d["zone_low"], minor_fibo_up) if minor_fibo_up else {"has_confluence": False, "has_ok_fibo": False, "fibo_tier": "NONE"}
        if min_c.get("has_confluence"):
            conf = dict(min_c)
        elif maj_c.get("has_confluence"):
            conf = dict(maj_c)
        elif min_c.get("has_ok_fibo"):
            conf = dict(min_c)
        elif maj_c.get("has_ok_fibo"):
            conf = dict(maj_c)
        else:
            conf = dict(min_c if minor_fibo_up else maj_c)
        d["fibo_confluence"] = conf
        d["is_h1_role_reversal"] = any(
            rr.zone_type == "RESISTANCE" and max(d["zone_low"], rr.price_low - rr_tol) <= min(d["zone_high"], rr.price_high + rr_tol)
            for rr in h1_rr
        )

    for s in supplies:
        maj_c = check_fibo_confluence(s["zone_high"], s["zone_low"], major_fibo_down) if major_fibo_down else {"has_confluence": False, "has_ok_fibo": False, "fibo_tier": "NONE"}
        min_c = check_fibo_confluence(s["zone_high"], s["zone_low"], minor_fibo_down) if minor_fibo_down else {"has_confluence": False, "has_ok_fibo": False, "fibo_tier": "NONE"}
        if min_c.get("has_confluence"):
            conf = dict(min_c)
        elif maj_c.get("has_confluence"):
            conf = dict(maj_c)
        elif min_c.get("has_ok_fibo"):
            conf = dict(min_c)
        elif maj_c.get("has_ok_fibo"):
            conf = dict(maj_c)
        else:
            conf = dict(min_c if minor_fibo_down else maj_c)
        s["fibo_confluence"] = conf
        s["is_h1_role_reversal"] = any(
            rr.zone_type == "SUPPORT" and max(s["zone_low"], rr.price_low - rr_tol) <= min(s["zone_high"], rr.price_high + rr_tol)
            for rr in h1_rr
        )

    return {
        "curr_price": curr_price,
        "atr": current_atr,
        "strong_bull": strong_bull,
        "strong_bear": strong_bear,
        "demands": demands,
        "supplies": supplies,
        "fibo_buy": minor_fibo_up or major_fibo_up,
        "fibo_sell": minor_fibo_down or major_fibo_down,
    }


def _legacy_select_candidate(
    primary_zone: Optional[Dict[str, Any]],
    all_zones: List[Dict[str, Any]],
    direction: str,
    curr_price: float,
    safe_atr: float,
    moat: float,
    spread: float,
    fibo_data: Optional[Dict[str, Any]],
    opp_zone: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Replicates exact BEFORE (Baseline) behavior: allows DEEP_ZONE_DISCOUNT even with NO Fibo support."""
    if not primary_zone:
        return None
    if _zone_has_golden_confluence(primary_zone, fibo_data):
        return _evaluate_zone_limit_candidate(
            primary_zone, direction, curr_price, safe_atr, moat, spread, fibo_data, opp_zone,
            entry_tier="GOLDEN_ZONE_CONFLUENCE", shifted_from_nearest=False,
        )
    max_shift_dist = max(1.50 * safe_atr, 10.0)
    for z in all_zones or []:
        if z is primary_zone:
            continue
        if not _zone_has_golden_confluence(z, fibo_data):
            continue
        zl, zh = float(z["zone_low"]), float(z["zone_high"])
        if direction == "BUY" and (zl >= curr_price or (curr_price - zh) > max_shift_dist):
            continue
        if direction == "SELL" and (zh <= curr_price or (zl - curr_price) > max_shift_dist):
            continue
        cand = _evaluate_zone_limit_candidate(
            z, direction, curr_price, safe_atr, moat, spread, fibo_data, opp_zone,
            entry_tier="NEARBY_GOLDEN_ZONE_SHIFT", shifted_from_nearest=True,
        )
        if cand["passes_hard_gate"]:
            return cand

    # Legacy Tier 3: pass entry_tier="TREND_PULLBACK_FIBO" wrapper ONLY to bypass new NO_FIBO_SUPPORT block,
    # then force 35% deep discount exactly like old DEEP_ZONE_DISCOUNT!
    zl, zh = float(primary_zone["zone_low"]), float(primary_zone["zone_high"])
    width = max(zh - zl, 0.0)
    raw_entry = round(zl + width * 0.35, 2) if direction == "BUY" else round(zh - width * 0.35, 2)
    if direction == "BUY":
        sl = round(zl - moat, 2)
        safe_bound = round(sl + MAX_GOLD_SL_USD - 0.05, 2)
        entry = round(min(raw_entry, safe_bound, zh), 2)
        sl_dist = round(entry - sl, 2)
        tp_cap = round(float(opp_zone["zone_low"]) - min(safe_atr * 0.25, 1.50), 2) if opp_zone and float(opp_zone["zone_low"]) > entry else round(entry + sl_dist * 2.2, 2)
        tp = round(min(entry + max(sl_dist * 2.0, 3.0), tp_cap), 2)
        rr = round((tp - entry) / sl_dist, 2) if sl_dist > 0 else 0.0
        ok = (entry < curr_price) and (0.20 <= sl_dist <= MAX_GOLD_SL_USD) and (rr >= MIN_GOLD_RR_RATIO) and (zl <= entry <= zh)
    else:
        sl = round(zh + moat + spread, 2)
        safe_bound = round(sl - MAX_GOLD_SL_USD + 0.05, 2)
        entry = round(max(raw_entry, safe_bound, zl), 2)
        sl_dist = round(sl - entry, 2)
        tp_cap = round(float(opp_zone["zone_high"]) + min(safe_atr * 0.25, 1.50), 2) if opp_zone and float(opp_zone["zone_high"]) < entry else round(entry - sl_dist * 2.2, 2)
        tp = round(max(entry - max(sl_dist * 2.0, 3.0), tp_cap), 2)
        rr = round((entry - tp) / sl_dist, 2) if sl_dist > 0 else 0.0
        ok = (entry > curr_price) and (0.20 <= sl_dist <= MAX_GOLD_SL_USD) and (rr >= MIN_GOLD_RR_RATIO) and (zl <= entry <= zh)

    return {
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "sl_distance_usd": sl_dist,
        "rr_ratio": rr,
        "passes_hard_gate": bool(ok),
        "entry_tier": "DEEP_ZONE_DISCOUNT",
        "zone_low": zl,
        "zone_high": zh,
        "fibo_tier": (primary_zone.get("fibo_confluence") or {}).get("fibo_tier", "NONE"),
    }


def simulate_gold_limit_strategy(
    bars_15m: List[Bar],
    bars_h1: List[Bar],
    bars_5m: Optional[List[Bar]] = None,
    require_fibo_filter: bool = True,
    strict_trend_and_fibo_anchor: bool = False,
    spread: float = 0.20,
    lot_size: float = 0.06,
    contract_size: float = 1.0,
    account_currency: str = "USC",
    ttl_m15_bars: int = 4,
    warmup_bars: int = 120,
) -> Dict[str, Any]:
    """
    Run deterministic zero-look-ahead simulation across historical M15 bars (with M5 sub-bar execution).
    """
    if strict_trend_and_fibo_anchor:
        mode_name = "FIBO_AND_TREND_GUARDED"
    else:
        mode_name = "FIBO_FILTERED" if require_fibo_filter else "BASELINE"
    # On Exness Cent (USC), 1 USD move on 1.0 oz = 100 USC
    ccy_mult = 100.0 if account_currency.upper() == "USC" else 1.0
    unit_value = lot_size * contract_size * ccy_mult

    trades: List[GoldBacktestTrade] = []
    skipped_no_fibo = 0
    cancelled_knife_or_tp = 0
    consumed_zones: set[tuple[str, float, float]] = set()

    open_pos: Optional[Dict[str, Any]] = None
    pending_lim: Optional[Dict[str, Any]] = None

    # Pre-index M5 bars by parent M15 interval for fast intra-bar resolution
    m5_list = bars_5m or []
    m5_ptr = 0
    h1_ptr = 0

    for i in range(warmup_bars, len(bars_15m)):
        bar15 = bars_15m[i]
        prev_close_t = bars_15m[i - 1].close_time
        cur_close_t = bar15.close_time

        # Collect M5 sub-bars strictly inside (prev_close_t, cur_close_t]
        sub_bars: List[Bar] = []
        while m5_ptr < len(m5_list) and m5_list[m5_ptr].close_time <= prev_close_t:
            m5_ptr += 1
        scan_ptr = m5_ptr
        while scan_ptr < len(m5_list) and m5_list[scan_ptr].close_time <= cur_close_t:
            sub_bars.append(m5_list[scan_ptr])
            scan_ptr += 1
        if not sub_bars:
            sub_bars = [bar15]

        # Advance H1 pointer strictly to confirmed H1 bars (close_time <= cur_close_t)
        while h1_ptr < len(bars_h1) and bars_h1[h1_ptr].close_time <= cur_close_t:
            h1_ptr += 1

        # 1. Process Open Position & Pending Limit across sub-bars chronologically
        for sb in sub_bars:
            # A. Manage Open Position
            if open_pos is not None:
                d = open_pos["direction"]
                sl = open_pos["current_sl"]
                tp = open_pos["tp"]
                entry = open_pos["entry"]
                init_risk = open_pos["risk"]

                if d == "BUY":
                    sl_hit = sb.low <= sl
                    tp_hit = sb.high >= tp
                else:
                    sl_hit = (sb.high + spread) >= sl
                    tp_hit = (sb.low + spread) <= tp

                # Conservative tie-breaker: SL wins if both hit in same sub-bar
                if sl_hit:
                    exit_px = sl
                    pnl_oz = (exit_px - entry) if d == "BUY" else (entry - exit_px)
                    reason = "BE_SL" if open_pos["be_locked"] else "SL"
                    trades.append(
                        GoldBacktestTrade(
                            mode=mode_name,
                            direction=d,
                            entry_tier=open_pos["entry_tier"],
                            fibo_tier=open_pos["fibo_tier"],
                            placed_time=open_pos["placed_time"],
                            entry_time=open_pos["entry_time"],
                            exit_time=sb.close_time.isoformat(),
                            entry_price=round(entry, 2),
                            initial_sl=round(open_pos["initial_sl"], 2),
                            final_sl=round(sl, 2),
                            tp_price=round(tp, 2),
                            exit_price=round(exit_px, 2),
                            risk_usd_per_oz=round(init_risk, 2),
                            pnl_usd_per_oz=round(pnl_oz, 2),
                            pnl_account_ccy=round(pnl_oz * unit_value, 2),
                            r_multiple=round(pnl_oz / init_risk, 2) if init_risk > 0 else 0.0,
                            exit_reason=reason,
                        )
                    )
                    open_pos = None
                elif tp_hit:
                    exit_px = tp
                    pnl_oz = (exit_px - entry) if d == "BUY" else (entry - exit_px)
                    trades.append(
                        GoldBacktestTrade(
                            mode=mode_name,
                            direction=d,
                            entry_tier=open_pos["entry_tier"],
                            fibo_tier=open_pos["fibo_tier"],
                            placed_time=open_pos["placed_time"],
                            entry_time=open_pos["entry_time"],
                            exit_time=sb.close_time.isoformat(),
                            entry_price=round(entry, 2),
                            initial_sl=round(open_pos["initial_sl"], 2),
                            final_sl=round(sl, 2),
                            tp_price=round(tp, 2),
                            exit_price=round(exit_px, 2),
                            risk_usd_per_oz=round(init_risk, 2),
                            pnl_usd_per_oz=round(pnl_oz, 2),
                            pnl_account_ccy=round(pnl_oz * unit_value, 2),
                            r_multiple=round(pnl_oz / init_risk, 2) if init_risk > 0 else 0.0,
                            exit_reason="TP",
                        )
                    )
                    open_pos = None
                else:
                    # Check +1.0R Auto Break-Even at sub-bar close
                    if not open_pos["be_locked"]:
                        fav = (sb.close - entry) if d == "BUY" else (entry - (sb.close + spread))
                        if fav >= init_risk:
                            open_pos["current_sl"] = round(entry + 0.30, 2) if d == "BUY" else round(entry - 0.30, 2)
                            open_pos["be_locked"] = True

            # B. Manage Pending Limit Order (only if no open position)
            elif pending_lim is not None:
                pd = pending_lim["direction"]
                p_entry = pending_lim["entry"]
                p_sl = pending_lim["sl"]
                p_tp = pending_lim["tp"]
                sb_range = sb.high - sb.low
                sb_body = abs(sb.close - sb.open)

                # Guard 1: Price hit TP before filling limit -> cancel stale limit
                if (pd == "BUY" and sb.high >= p_tp) or (pd == "SELL" and (sb.low + spread) <= p_tp):
                    pending_lim = None
                    cancelled_knife_or_tp += 1
                    continue

                # Guard 2: Knife Guard — violent marubozu candle (>= 1.5x M15 ATR * 0.6) slamming against zone before fill
                violent_against = (
                    sb_range >= (pending_lim["atr"] * 1.15)
                    and (sb_body / max(sb_range, 0.01)) >= 0.72
                    and ((pd == "BUY" and sb.close < sb.open) or (pd == "SELL" and sb.close > sb.open))
                )
                if violent_against:
                    pending_lim = None
                    cancelled_knife_or_tp += 1
                    continue

                # Check Limit Fill (Spread-aware: BUY Limit fills on Ask <= entry; SELL Limit fills on Bid >= entry)
                filled = ((sb.low + spread) <= p_entry) if pd == "BUY" else (sb.high >= p_entry)
                if filled:
                    consumed_zones.add(pending_lim["zone_key"])
                    open_pos = {
                        "direction": pd,
                        "entry": p_entry,
                        "initial_sl": p_sl,
                        "current_sl": p_sl,
                        "tp": p_tp,
                        "risk": abs(p_entry - p_sl),
                        "be_locked": False,
                        "entry_tier": pending_lim["entry_tier"],
                        "fibo_tier": pending_lim["fibo_tier"],
                        "placed_time": pending_lim["placed_time"],
                        "entry_time": sb.close_time.isoformat(),
                    }
                    pending_lim = None
                    # Check immediate intra-bar SL after fill on same sub-bar (conservative!)
                    same_bar_sl = (sb.low <= p_sl) if pd == "BUY" else ((sb.high + spread) >= p_sl)
                    if same_bar_sl:
                        pnl_oz = (p_sl - p_entry) if pd == "BUY" else (p_entry - p_sl)
                        trades.append(
                            GoldBacktestTrade(
                                mode=mode_name,
                                direction=pd,
                                entry_tier=open_pos["entry_tier"],
                                fibo_tier=open_pos["fibo_tier"],
                                placed_time=open_pos["placed_time"],
                                entry_time=open_pos["entry_time"],
                                exit_time=sb.close_time.isoformat(),
                                entry_price=round(p_entry, 2),
                                initial_sl=round(p_sl, 2),
                                final_sl=round(p_sl, 2),
                                tp_price=round(p_tp, 2),
                                exit_price=round(p_sl, 2),
                                risk_usd_per_oz=round(open_pos["risk"], 2),
                                pnl_usd_per_oz=round(pnl_oz, 2),
                                pnl_account_ccy=round(pnl_oz * unit_value, 2),
                                r_multiple=-1.0,
                                exit_reason="SL",
                            )
                        )
                        open_pos = None

        # Expire pending limit after TTL or zone break at M15 bar close
        if pending_lim is not None:
            pending_lim["bars_alive"] += 1
            z_broken = (
                (pending_lim["direction"] == "BUY" and bar15.close < pending_lim["zone_low"])
                or (pending_lim["direction"] == "SELL" and bar15.close > pending_lim["zone_high"])
            )
            if pending_lim["bars_alive"] >= ttl_m15_bars or z_broken:
                pending_lim = None

        # 2. Evaluate New Limit Candidate at M15 Close (only when flat and no pending order)
        if open_pos is not None or pending_lim is not None:
            continue

        bkk_dt = cur_close_t.astimezone(TZ_BKK)
        # Skip Daily Rollover Blackout (04:00 - 06:10 BKK)
        if bkk_dt.hour in (4, 5) or (bkk_dt.hour == 6 and bkk_dt.minute <= 10):
            continue

        hist_15m = bars_15m[max(0, i - 199): i + 1]
        hist_h1 = bars_h1[max(0, h1_ptr - 150): h1_ptr]
        if len(hist_15m) < 60:
            continue

        snap = _build_snapshot_structure(hist_15m, hist_h1)
        curr_px = snap["curr_price"]
        atr = snap["atr"]
        moat = max(round(min(atr * 0.18, 1.50), 2), 0.50)

        # Skip placing right on a violent M15 impulse bar (>= 1.6x ATR)
        if (bar15.high - bar15.low) >= (atr * 1.60):
            continue

        nd = snap["demands"][0] if snap["demands"] else None
        ns = snap["supplies"][0] if snap["supplies"] else None

        dist_d = abs(curr_px - nd["zone_high"]) if nd else 99999.0
        dist_s = abs(curr_px - ns["zone_low"]) if ns else 99999.0

        # Evaluate BUY candidate if Demand is within 0.80x ATR proximity and closer than Supply
        chosen_cand: Optional[Dict[str, Any]] = None
        chosen_dir: Optional[str] = None
        chosen_fibo_tier: str = "NONE"

        if nd and dist_d <= (atr * 0.80) and dist_d <= dist_s and curr_px > nd["zone_low"]:
            is_hq = ("1H" in nd.get("timeframe", "")) or (nd.get("fibo_confluence") or {}).get("has_confluence", False) or nd.get("is_h1_role_reversal", False)
            ct_blocked = snap["strong_bear"] if strict_trend_and_fibo_anchor else (snap["strong_bear"] and not is_hq)
            if not ct_blocked:
                opp_s = next((s for s in snap["supplies"] if s["zone_low"] > curr_px), None)
                headroom = (opp_s["zone_low"] - curr_px) if opp_s else 999.0
                if headroom >= (atr * 1.0):
                    if require_fibo_filter:
                        cand = _select_fibo_prioritized_zone_candidate(
                            nd, snap["demands"], "BUY", curr_px, atr, moat, spread, snap["fibo_buy"], opp_s
                        )
                        if cand and cand["entry_tier"] == "NO_FIBO_SUPPORT":
                            skipped_no_fibo += 1
                    else:
                        cand = _legacy_select_candidate(
                            nd, snap["demands"], "BUY", curr_px, atr, moat, spread, snap["fibo_buy"], opp_s
                        )
                    if cand and cand.get("passes_hard_gate"):
                        if strict_trend_and_fibo_anchor and cand.get("clamped_to_sl_cap"):
                            cand = None
                        else:
                            chosen_cand = cand
                            chosen_dir = "BUY"
                            chosen_fibo_tier = (nd.get("fibo_confluence") or {}).get("fibo_tier", "NONE")

        # Evaluate SELL candidate if Supply is within 0.80x ATR proximity
        if chosen_cand is None and ns and dist_s <= (atr * 0.80) and curr_px < ns["zone_high"]:
            is_hq = ("1H" in ns.get("timeframe", "")) or (ns.get("fibo_confluence") or {}).get("has_confluence", False) or ns.get("is_h1_role_reversal", False)
            ct_blocked = snap["strong_bull"] if strict_trend_and_fibo_anchor else (snap["strong_bull"] and not is_hq)
            if not ct_blocked:
                opp_d = next((d for d in snap["demands"] if d["zone_high"] < curr_px), None)
                headroom = (curr_px - opp_d["zone_high"]) if opp_d else 999.0
                if headroom >= (atr * MIN_HEADROOM_ATR_MULT):
                    if require_fibo_filter:
                        cand = _select_fibo_prioritized_zone_candidate(
                            ns, snap["supplies"], "SELL", curr_px, atr, moat, spread, snap["fibo_sell"], opp_d
                        )
                        if cand and cand["entry_tier"] == "NO_FIBO_SUPPORT":
                            skipped_no_fibo += 1
                    else:
                        cand = _legacy_select_candidate(
                            ns, snap["supplies"], "SELL", curr_px, atr, moat, spread, snap["fibo_sell"], opp_d
                        )
                    if cand and cand.get("passes_hard_gate"):
                        if strict_trend_and_fibo_anchor and cand.get("clamped_to_sl_cap"):
                            cand = None
                        else:
                            chosen_cand = cand
                            chosen_dir = "SELL"
                            chosen_fibo_tier = (ns.get("fibo_confluence") or {}).get("fibo_tier", "NONE")

        if chosen_cand and chosen_dir:
            # Workflow Rule 1 (ท่าที่ 2): Skip placing blind wide-zone bottom limit if clamped far off Fibo
            if chosen_cand.get("clamped_to_sl_cap") and abs(curr_px - float(chosen_cand["entry"])) > 6.50:
                continue
            z_key = (chosen_dir, round(float(chosen_cand["zone_low"]), 1), round(float(chosen_cand["zone_high"]), 1))
            if z_key not in consumed_zones:
                pending_lim = {
                    "direction": chosen_dir,
                    "entry": float(chosen_cand["entry"]),
                    "sl": float(chosen_cand["sl"]),
                    "tp": float(chosen_cand["tp"]),
                    "zone_low": float(chosen_cand["zone_low"]),
                    "zone_high": float(chosen_cand["zone_high"]),
                    "zone_key": z_key,
                    "entry_tier": chosen_cand["entry_tier"],
                    "fibo_tier": chosen_fibo_tier,
                    "atr": atr,
                    "bars_alive": 0,
                    "placed_time": cur_close_t.isoformat(),
                }

    # Summarize metrics
    total = len(trades)
    wins = [t for t in trades if t.pnl_usd_per_oz > 0]
    losses = [t for t in trades if t.pnl_usd_per_oz <= 0]
    gross_win = sum(t.pnl_account_ccy for t in wins)
    gross_loss = abs(sum(t.pnl_account_ccy for t in losses))
    net_pnl_ccy = round(sum(t.pnl_account_ccy for t in trades), 2)
    net_pnl_oz = round(sum(t.pnl_usd_per_oz for t in trades), 2)
    total_r = round(sum(t.r_multiple for t in trades), 2)
    win_rate = round((len(wins) / total) * 100.0, 2) if total > 0 else 0.0
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (99.99 if gross_win > 0 else 0.0)

    # Max Drawdown in Account Currency & R
    eq = 0.0
    peak = 0.0
    max_dd_ccy = 0.0
    eq_r = 0.0
    peak_r = 0.0
    max_dd_r = 0.0
    for t in trades:
        eq += t.pnl_account_ccy
        peak = max(peak, eq)
        max_dd_ccy = max(max_dd_ccy, peak - eq)
        eq_r += t.r_multiple
        peak_r = max(peak_r, eq_r)
        max_dd_r = max(max_dd_r, peak_r - eq_r)

    tier_stats: Dict[str, Dict[str, Any]] = {}
    for t in trades:
        st = tier_stats.setdefault(t.entry_tier, {"trades": 0, "wins": 0, "total_r": 0.0, "pnl_usc": 0.0})
        st["trades"] += 1
        if t.pnl_usd_per_oz > 0:
            st["wins"] += 1
        st["total_r"] = round(st["total_r"] + t.r_multiple, 2)
        st["pnl_usc"] = round(st["pnl_usc"] + t.pnl_account_ccy, 2)

    return {
        "mode": mode_name,
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "be_exits": sum(1 for t in trades if t.exit_reason == "BE_SL"),
        "win_rate_pct": win_rate,
        "total_r": total_r,
        "avg_r_per_trade": round(total_r / total, 3) if total > 0 else 0.0,
        "net_pnl_usd_per_oz": net_pnl_oz,
        "net_pnl_account_ccy": net_pnl_ccy,
        "profit_factor": pf,
        "max_drawdown_account_ccy": round(max_dd_ccy, 2),
        "max_drawdown_r": round(max_dd_r, 2),
        "skipped_shallow_no_fibo": skipped_no_fibo,
        "cancelled_knife_or_missed_tp": cancelled_knife_or_tp,
        "stats_by_tier": tier_stats,
        "sample_trades": [asdict(t) for t in trades[-8:]],
    }


def run_comparison(bars_count: int = 1500) -> Dict[str, Any]:
    sym, contract_size, acc_ccy, data = fetch_mt5_gold_bars(bars_15m_count=bars_count)
    bars_15m = data["M15"]
    bars_h1 = data["H1"]
    bars_5m = data["M5"]

    if len(bars_15m) < 200:
        raise RuntimeError(f"Insufficient M15 bars fetched ({len(bars_15m)}).")

    start_dt = bars_15m[120].open_time.isoformat()
    end_dt = bars_15m[-1].close_time.isoformat()

    base_res = simulate_gold_limit_strategy(
        bars_15m=bars_15m,
        bars_h1=bars_h1,
        bars_5m=bars_5m,
        require_fibo_filter=False,
        contract_size=contract_size,
        account_currency=acc_ccy,
    )
    fibo_res = simulate_gold_limit_strategy(
        bars_15m=bars_15m,
        bars_h1=bars_h1,
        bars_5m=bars_5m,
        require_fibo_filter=True,
        contract_size=contract_size,
        account_currency=acc_ccy,
    )
    fibo_trend_res = simulate_gold_limit_strategy(
        bars_15m=bars_15m,
        bars_h1=bars_h1,
        bars_5m=bars_5m,
        require_fibo_filter=True,
        strict_trend_and_fibo_anchor=True,
        contract_size=contract_size,
        account_currency=acc_ccy,
    )

    return {
        "symbol": sym,
        "account_currency": acc_ccy,
        "contract_size": contract_size,
        "lot_size": 0.06,
        "m15_bars_total": len(bars_15m),
        "m5_bars_total": len(bars_5m),
        "h1_bars_total": len(bars_h1),
        "period_start_utc": start_dt,
        "period_end_utc": end_dt,
        "baseline_no_filter": base_res,
        "fibo_382_786_filtered": fibo_res,
        "fibo_plus_trend_guarded": fibo_trend_res,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real MT5 Historical XAU/USD Limit-First Backtester")
    parser.add_argument("--bars", type=int, default=1500, help="Number of M15 bars to fetch from MT5")
    args = parser.parse_args()

    report = run_comparison(bars_count=args.bars)
    print(json.dumps(report, ensure_ascii=False, indent=2))
