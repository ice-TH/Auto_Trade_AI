"""
XAU/USD (Gold) Strategy Module
Designed for Antigravity AI to analyze XAUUSD / XAUUSDm / XAUUSDc:
- Support & Resistance with Role Reversal (Broken Support -> Resistance, Broken Resistance -> Support)
- Demand & Supply Zones: DBR (Drop-Base-Rally), RBR (Rally-Base-Rally), RBD (Rally-Base-Drop), DBD (Drop-Base-Drop)
  with 1-4 candle Base detection, Edge-Anchored Clamping, and Permanent Broken Zone Invalidation (No Zombie Zones)
- Direction-Aware Multi-Swing ZigZag Fibonacci (Upswing Buy Discount vs Downswing Sell Premium)
- Confirmed-Bar Rejection Trigger vs Real-Time Live Danger Guard (Falling Knife / Rocket Surge / Volatility Spike)
- DST-Aware Trading Session & London x New York Overlap Detection
- Spread-aware SL (Moat buffer + Spread on SELL) and TP (Front-running)
- Strictly NO Order Block (OB) logic included per user instruction.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import logging

from src.data.base import Bar, TimeFrame
from src.data.mt5_adapter import MT5DataAdapter
from src.analysis.indicators import calculate_atr, calculate_ema, calculate_sma
from src.analysis.swings import analyze_market_structure
from src.analysis.zones import build_sr_zones
from src.risk.news_guard import is_volatility_spike

logger = logging.getLogger("gold_strategy")

TZ_BANGKOK = ZoneInfo("Asia/Bangkok")
TZ_LONDON = ZoneInfo("Europe/London")
TZ_NEW_YORK = ZoneInfo("America/New_York")

# Quantitative Safety Thresholds for Gold (XAU/USD) Intraday
MIN_GOLD_SL_USD = 2.00        # Minimum SL distance ($2.00) to avoid Gold noise stop-hunts
MAX_GOLD_SL_USD = 8.00        # Hard Stop Loss cap ($8.00 USD max per [XAU-RULE-09] & [XAU-RULE-12])
MIN_GOLD_RR_RATIO = 1.50      # Minimum Risk:Reward ratio required to issue Buy/Sell setup
MIN_HEADROOM_ATR_MULT = 1.50  # Must have at least 1.5x ATR space before nearest downside obstacle
MAX_ZONE_RETESTS = 3          # Exhausted zones (>3 retests) excluded from automatic limit pre-placement


@dataclass
class ZigZagPivot:
    index: int
    bar_time: Any
    price: float
    pivot_type: int  # 1 = HIGH, -1 = LOW


def detect_zigzag_pivots(bars: List[Bar], pivot_legs: int = 10, min_deviation_pct: float = 1.0) -> List[ZigZagPivot]:
    """
    Robust ZigZag engine directly adapted from PineScript V3 (pinescript_FIBO_1.txt).
    - Requires pivot_legs bars on left and right
    - Reversal leg must exceed min_deviation_pct (default 0.8% ~ $25-$30 for Gold)
    - Automatically updates same-direction pivots with more extreme price
    - Memory bounded, zero look-ahead bias
    """
    if len(bars) < (2 * pivot_legs + 1):
        return []

    pv_price: List[float] = []
    pv_index: List[int] = []
    pv_type: List[int] = []
    pv_time: List[Any] = []

    def add_pivot(price: float, bidx: int, ptype: int, btime: Any):
        n = len(pv_price)
        if n == 0:
            pv_price.append(price)
            pv_index.append(bidx)
            pv_type.append(ptype)
            pv_time.append(btime)
        else:
            last_p = pv_price[-1]
            last_b = pv_index[-1]
            last_t = pv_type[-1]
            if ptype == last_t:
                # Same direction -> keep more extreme value
                better = price > last_p if ptype == 1 else price < last_p
                if better and bidx >= last_b:
                    pv_price[-1] = price
                    pv_index[-1] = bidx
                    pv_time[-1] = btime
            elif bidx > last_b:
                # Reversal direction -> must pass deviation threshold
                denom = max(abs(last_p), 0.01)
                dev = (abs(price - last_p) / denom) * 100.0
                if dev >= min_deviation_pct or n == 1:
                    pv_price.append(price)
                    pv_index.append(bidx)
                    pv_type.append(ptype)
                    pv_time.append(btime)

    total_bars = len(bars)
    for i in range(pivot_legs, total_bars - pivot_legs):
        curr_h = bars[i].high
        curr_l = bars[i].low
        btime = bars[i].open_time

        # Check Pivot High
        is_h = True
        for k in range(1, pivot_legs + 1):
            if bars[i - k].high >= curr_h or bars[i + k].high > curr_h:
                is_h = False
                break

        # Check Pivot Low
        is_l = True
        for k in range(1, pivot_legs + 1):
            if bars[i - k].low <= curr_l or bars[i + k].low < curr_l:
                is_l = False
                break

        if is_h and is_l:
            last_t = pv_type[-1] if pv_type else 0
            if last_t == 1:
                add_pivot(curr_l, i, -1, btime)
            else:
                add_pivot(curr_h, i, 1, btime)
        elif is_h:
            add_pivot(curr_h, i, 1, btime)
        elif is_l:
            add_pivot(curr_l, i, -1, btime)

    return [
        ZigZagPivot(index=pv_index[i], bar_time=pv_time[i], price=pv_price[i], pivot_type=pv_type[i])
        for i in range(len(pv_price))
    ]


def calculate_fibonacci_retracement(
    swing_high: float,
    swing_low: float,
    label: str = "Major",
    direction: str = "UP"
) -> Dict[str, Any]:
    """
    Direction-aware Fibonacci Retracement levels including 0.65 (Optimal Trade Entry - OTE).
    Matches PineScript V3 formula: `fibB - (fibB - fibA) * lv`
    - direction == "UP" (Low -> High impulse, retracing downward into Discount):
      * 0.0% = swing_high, 100% = swing_low
      * 61.8% = high - 0.618 * diff | 65.0% OTE = high - 0.650 * diff | 78.6% = high - 0.786 * diff
    - direction == "DOWN" (High -> Low impulse, retracing upward into Premium):
      * 0.0% = swing_low, 100% = swing_high
      * 61.8% = low + 0.618 * diff | 65.0% OTE = low + 0.650 * diff | 78.6% = low + 0.786 * diff
    """
    diff = swing_high - swing_low
    if diff <= 0:
        return {}

    dir_norm = direction.upper()
    if dir_norm == "DOWN":
        f236 = round(swing_low + 0.236 * diff, 2)
        f382 = round(swing_low + 0.382 * diff, 2)
        f500 = round(swing_low + 0.500 * diff, 2)
        f618 = round(swing_low + 0.618 * diff, 2)
        f650 = round(swing_low + 0.650 * diff, 2)
        f786 = round(swing_low + 0.786 * diff, 2)
        gz_high = f786
        gz_low = f618
    else:
        dir_norm = "UP"
        f236 = round(swing_high - 0.236 * diff, 2)
        f382 = round(swing_high - 0.382 * diff, 2)
        f500 = round(swing_high - 0.500 * diff, 2)
        f618 = round(swing_high - 0.618 * diff, 2)
        f650 = round(swing_high - 0.650 * diff, 2)
        f786 = round(swing_high - 0.786 * diff, 2)
        gz_high = f618
        gz_low = f786

    return {
        "label": label,
        "direction": dir_norm,
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
        "fibo_236": f236,
        "fibo_382": f382,
        "fibo_500": f500,
        "fibo_618": f618,
        "fibo_650": f650,
        "fibo_786": f786,
        "golden_zone_high": gz_high,
        "golden_zone_mid": f650,
        "golden_zone_low": gz_low,
        "diff": round(diff, 2)
    }


def check_fibo_confluence(zone_high: float, zone_low: float, fibo_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluates Fibonacci retracement support for a Demand/Supply Zone:
    - Tier 1 (GOLDEN_ZONE): Overlaps 61.8% - 78.6% (has_confluence=True, has_ok_fibo=True)
    - Tier 2 (TREND_PULLBACK): Overlaps 38.2% - 61.8% band including 38.2% & 50.0% (has_confluence=False, has_ok_fibo=True)
    - NONE: Shallower than 38.2% (e.g. above 23.6%) or beyond 78.6% (has_confluence=False, has_ok_fibo=False)
    """
    if not fibo_data or "golden_zone_high" not in fibo_data:
        return {
            "has_confluence": False,
            "has_ok_fibo": False,
            "fibo_tier": "NONE",
            "overlap_pct": 0.0,
            "reason": "No Fibo data",
        }

    gz_high = max(float(fibo_data["golden_zone_high"]), float(fibo_data["golden_zone_low"]))
    gz_low = min(float(fibo_data["golden_zone_high"]), float(fibo_data["golden_zone_low"]))
    label = fibo_data.get("label", "")
    fibo_dir = fibo_data.get("direction", "UP")
    fibo_650 = fibo_data.get("fibo_650")
    fibo_618 = fibo_data.get("fibo_618")
    fibo_500 = fibo_data.get("fibo_500")
    fibo_382 = fibo_data.get("fibo_382")

    z_low = min(float(zone_low), float(zone_high))
    z_high = max(float(zone_low), float(zone_high))
    zone_size = max(z_high - z_low, 0.01)

    # 1. Check Golden Zone (61.8% - 78.6%)
    overlap_low = max(z_low, gz_low)
    overlap_high = min(z_high, gz_high)
    if overlap_high >= overlap_low:
        overlap_size = overlap_high - overlap_low
        overlap_pct = min(round((overlap_size / zone_size) * 100.0, 1), 100.0)
        target_lv = fibo_650 if (fibo_650 is not None and z_low <= float(fibo_650) <= z_high) else round((overlap_high + overlap_low) / 2.0, 2)
        return {
            "has_confluence": True,
            "has_ok_fibo": True,
            "fibo_tier": "GOLDEN_ZONE",
            "fibo_label": label,
            "fibo_direction": fibo_dir,
            "fibo_650": fibo_650,
            "fibo_target_level": round(float(target_lv), 2),
            "overlap_high": round(overlap_high, 2),
            "overlap_low": round(overlap_low, 2),
            "overlap_mid": round((overlap_high + overlap_low) / 2.0, 2),
            "overlap_pct": overlap_pct,
            "reason": f"ซ้อนทับ {label} Golden Zone 61.8%-78.6% ({overlap_low:.2f} - {overlap_high:.2f}) {overlap_pct}%",
        }

    # 2. Check OK Trend Pullback Fibo Zone (38.2% - 61.8%, covering 38.2% & 50.0% without gap to 61.8%)
    if fibo_382 is not None and fibo_618 is not None:
        pb_low = min(float(fibo_382), float(fibo_618))
        pb_high = max(float(fibo_382), float(fibo_618))
        pb_ov_low = max(z_low, pb_low)
        pb_ov_high = min(z_high, pb_high)
        if pb_ov_high >= pb_ov_low:
            pb_ov_size = pb_ov_high - pb_ov_low
            pb_ov_pct = min(round((pb_ov_size / zone_size) * 100.0, 1), 100.0)
            pb_mid = round((pb_ov_high + pb_ov_low) / 2.0, 2)
            if fibo_500 is not None and z_low <= float(fibo_500) <= z_high:
                target_lv = round(float(fibo_500), 2)
                lv_tag = "50.0%"
            elif fibo_382 is not None and z_low <= float(fibo_382) <= z_high:
                target_lv = round(float(fibo_382), 2)
                lv_tag = "38.2%"
            else:
                target_lv = pb_mid
                lv_tag = "38.2%-50.0%"
            return {
                "has_confluence": False,
                "has_ok_fibo": True,
                "fibo_tier": "TREND_PULLBACK",
                "fibo_label": label,
                "fibo_direction": fibo_dir,
                "fibo_650": fibo_650,
                "fibo_target_level": target_lv,
                "overlap_high": round(pb_ov_high, 2),
                "overlap_low": round(pb_ov_low, 2),
                "overlap_mid": pb_mid,
                "overlap_pct": pb_ov_pct,
                "reason": f"ซ้อนทับ {label} Fibo Pullback {lv_tag} ({pb_ov_low:.2f} - {pb_ov_high:.2f}) {pb_ov_pct}%",
            }

    dist = min(abs(z_low - gz_high), abs(z_high - gz_low))
    return {
        "has_confluence": False,
        "has_ok_fibo": False,
        "fibo_tier": "NONE",
        "fibo_label": label,
        "fibo_direction": fibo_dir,
        "overlap_pct": 0.0,
        "distance": round(dist, 2),
        "reason": f"ไม่ซ้อนทับ {label} Fibo 38.2%-78.6% (ห่าง Golden Zone {dist:.2f} USD)",
    }


def detect_trading_session(utc_now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Detects the current active Trading Session(s) with DST awareness for London & New York,
    displayed alongside Bangkok Time (UTC+7).
    """
    if utc_now is None:
        utc_now = datetime.now(timezone.utc)
    elif utc_now.tzinfo is None:
        utc_now = utc_now.replace(tzinfo=timezone.utc)

    bkk_time = utc_now.astimezone(TZ_BANGKOK)
    lon_time = utc_now.astimezone(TZ_LONDON)
    ny_time = utc_now.astimezone(TZ_NEW_YORK)

    bkk_hour = bkk_time.hour
    bkk_float = bkk_hour + bkk_time.minute / 60.0
    lon_float = lon_time.hour + lon_time.minute / 60.0
    ny_float = ny_time.hour + ny_time.minute / 60.0

    active_sessions = []

    # Sydney: ~05:00 - 14:00 BKK
    if 5.0 <= bkk_float < 14.0:
        active_sessions.append("Sydney (ออสเตรเลีย)")

    # Tokyo: 06:00 - 15:00 BKK (08:00 - 17:00 JST, no DST)
    if 6.0 <= bkk_float < 15.0:
        active_sessions.append("Tokyo (เอเชีย)")

    # London: 08:00 - 16:30 London Local Time (auto-handles BST/GMT -> 14:00-22:30 or 15:00-23:30 BKK)
    is_london = (8.0 <= lon_float < 16.5)
    if is_london:
        active_sessions.append("London (ยุโรป)")

    # New York Gold/FX active session: 08:00 - 17:00 NY Local Time (auto-handles EDT/EST)
    is_ny = (8.0 <= ny_float < 17.0)
    if is_ny:
        active_sessions.append("New York (อเมริกา)")

    # London x New York Overlap: Both London & New York open simultaneously
    is_overlap = (is_london and is_ny)

    liquidity_status = "NORMAL"
    if is_overlap:
        liquidity_status = "PEAK_OVERLAP"
        session_desc = "🔥 ช่วงเวลาทอง (London × New York Overlap): ปริมาณซื้อขายและสภาพคล่องสูงสุดในรอบวัน ความผันผวนสูงมาก"
    elif is_london or is_ny:
        liquidity_status = "HIGH"
        session_desc = f"ช่วงตลาดหลัก ({', '.join(active_sessions)}): สภาพคล่องสูง ทิศทางชัดเจน"
    elif active_sessions:
        liquidity_status = "LOW_MODERATE"
        session_desc = f"ช่วงตลาดเอเชีย/ออสเตรเลีย ({', '.join(active_sessions)}): สภาพคล่องปานกลาง-ต่ำ ระวัง Sideway กรอบแคบ"
    else:
        liquidity_status = "OFF_HOURS"
        session_desc = "ช่วงพักตลาดหลัก (Rollover / Off-Hours): สภาพคล่องต่ำ สเปรดอาจถ่างกว้าง"

    return {
        "bkk_time": bkk_time.strftime("%H:%M:%S"),
        "bkk_hour": bkk_hour,
        "ny_time": ny_time.strftime("%H:%M:%S"),
        "active_sessions": active_sessions,
        "is_overlap": is_overlap,
        "liquidity_status": liquidity_status,
        "session_description": session_desc
    }


def clamp_zone_size(
    top: float,
    bottom: float,
    atr: float,
    max_atr_mult: float = 1.5,
    zone_type: str = "NEUTRAL"
) -> Tuple[float, float]:
    """
    Prevents oversized Demand/Supply zones from bloating while preserving the true structural SL anchor:
    - DEMAND: Anchors `bottom` (true base low for SL placement) and clamps `top` down to `bottom + max_size`.
    - SUPPLY: Anchors `top` (true base high for SL placement) and clamps `bottom` up to `top - max_size`.
    - NEUTRAL: Clamps symmetrically.
    """
    size = top - bottom
    max_size = atr * max_atr_mult
    if size > max_size and max_size > 0:
        ztype = zone_type.upper()
        if ztype == "DEMAND":
            top = bottom + max_size
        elif ztype == "SUPPLY":
            bottom = top - max_size
        else:
            diff = size - max_size
            top -= diff / 2.0
            bottom += diff / 2.0
    return round(top, 2), round(bottom, 2)


def combine_overlapping_zones(zones: List[Dict[str, Any]], atr: float) -> List[Dict[str, Any]]:
    """
    Combines overlapping or touching zones of the same type into a single high-confluence zone
    while preserving the outer structural edge for SL safety.
    """
    if not zones:
        return []

    combined = []
    skip_indices = set()

    for i in range(len(zones)):
        if i in skip_indices:
            continue
        cur = dict(zones[i])
        ztype = cur.get("type", "NEUTRAL")
        merged_any = False
        for j in range(i + 1, len(zones)):
            if j in skip_indices:
                continue
            other = zones[j]
            if other.get("type", ztype) != ztype:
                continue
            # Check overlap or touching within 0.25x ATR
            touches = not (
                cur["zone_low"] > other["zone_high"] + (atr * 0.25)
                or cur["zone_high"] < other["zone_low"] - (atr * 0.25)
            )
            if touches:
                merged_any = True
                new_top = max(cur["zone_high"], other["zone_high"])
                new_bottom = min(cur["zone_low"], other["zone_low"])
                # Only clamp if merging distinct zones caused excessive bloat; if identical zone across TFs, preserve original bounds
                if (new_top != cur["zone_high"] or new_bottom != cur["zone_low"]) and (new_top - new_bottom) > (atr * 2.0):
                    new_top, new_bottom = clamp_zone_size(new_top, new_bottom, atr, max_atr_mult=2.0, zone_type=ztype)
                cur["zone_high"] = new_top
                cur["zone_low"] = new_bottom
                cur["zone_mid"] = round((new_top + new_bottom) / 2.0, 2)
                cur["confluence"] = cur.get("confluence", 1) + other.get("confluence", 1)
                cur["retest_count"] = min(cur.get("retest_count", 0), other.get("retest_count", 0))
                cur["tested"] = cur["retest_count"] > 0
                other_tf = other.get("timeframe", "")
                if other_tf and other_tf not in cur.get("timeframe", ""):
                    cur["timeframe"] = f"{cur.get('timeframe', '')} & {other_tf}".strip(" &")
                skip_indices.add(j)

        combined.append(cur)

    return combined


def detect_demand_supply_zones(
    bars: List[Bar],
    min_bars: int = 15,
    timeframe_label: str = "15m",
    atr_val: Optional[float] = None
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Identifies Demand & Supply Zones based on Price Action candle formations (Strictly NO Order Blocks):
    - Demand: Drop-Base-Rally (DBR) and Rally-Base-Rally (RBR)
    - Supply: Rally-Base-Drop (RBD) and Drop-Base-Drop (DBD)
    Upgrades:
    1. Supports 1 to 4 consolidation Base candles before an impulsive departure (>= 1.5x avg body).
    2. Edge-anchored clamping (`clamp_zone_size`) so Demand `zone_low` / Supply `zone_high` stays intact for SL.
    3. Sequential bar-by-bar invalidation (`bars[impulse_idx + 1:]`): Once broken by a candle close,
       a zone is permanently dead (eliminates Zombie Zones).
    4. Tracks `retest_count` and `freshness` across subsequent pullbacks.
    """
    if len(bars) < min_bars:
        return {"demand_zones": [], "supply_zones": []}

    demand_zones: List[Dict[str, Any]] = []
    supply_zones: List[Dict[str, Any]] = []

    # Calculate average body size and ATR
    body_sizes = [abs(b.close - b.open) for b in bars[-40:]]
    avg_body = max(sum(body_sizes) / max(len(body_sizes), 1), 0.05)

    if atr_val is None or atr_val <= 0:
        tr_list = []
        for k in range(1, len(bars)):
            h_l = bars[k].high - bars[k].low
            h_pc = abs(bars[k].high - bars[k - 1].close)
            l_pc = abs(bars[k].low - bars[k - 1].close)
            tr_list.append(max(h_l, h_pc, l_pc))
        atr_val = (sum(tr_list[-14:]) / 14.0) if len(tr_list) >= 14 else avg_body * 1.5

    # Only scan confirmed historical impulse candles (exclude still-forming live bar if > 3 bars)
    last_scan_idx = len(bars) - 1 if bars[-1].is_confirmed else max(len(bars) - 2, 2)
    last_demand_idx = -5
    last_supply_idx = -5

    for i in range(2, last_scan_idx + 1):
        leg2 = bars[i]
        leg2_body = leg2.close - leg2.open

        # Require genuine institutional momentum departure (>= 1.5x average body)
        is_bull_impulse = leg2_body >= (avg_body * 1.5)
        is_bear_impulse = leg2_body <= -(avg_body * 1.5)
        if not (is_bull_impulse or is_bear_impulse):
            continue

        # Collect 1 to 4 tight base candles immediately preceding impulse bar `i`
        base_bars: List[Bar] = []
        idx_b = i - 1
        while idx_b >= 1 and len(base_bars) < 4:
            cand = bars[idx_b]
            cand_body = abs(cand.close - cand.open)
            cand_range = cand.high - cand.low
            if cand_body <= (avg_body * 1.25) and cand_range <= (atr_val * 1.8):
                base_bars.insert(0, cand)
                idx_b -= 1
            else:
                break

        if not base_bars or idx_b < 0:
            continue

        # Total cluster span of base must remain compact (not a wide trending leg)
        raw_high = max(b.high for b in base_bars)
        raw_low = min(b.low for b in base_bars)
        if (raw_high - raw_low) > (atr_val * 2.2):
            # Fallback to single tightest candle right before impulse
            single = base_bars[-1]
            raw_high = single.high
            raw_low = single.low
            base_bars = [single]
            idx_b = i - 2

        if idx_b < 0:
            continue
        leg1 = bars[idx_b]
        leg1_body = leg1.close - leg1.open
        base_start_bar = base_bars[0]

        # 1. Demand Zone Evaluation
        if is_bull_impulse and leg2.close > raw_high and (i - last_demand_idx) >= 3:
            pattern_type = "DBR" if leg1_body < 0 else "RBR"
            zone_high, zone_low = clamp_zone_size(raw_high, raw_low, atr_val, max_atr_mult=1.5, zone_type="DEMAND")

            # Sequential Lifecycle Check across ALL bars after departure
            is_broken = False
            retest_count = 0
            left_zone = True  # leg2 closed above raw_high >= zone_high
            for sub_b in bars[i + 1:]:
                # Close below Demand floor permanently invalidates the zone [XAU-RULE-15]
                if sub_b.close < zone_low:
                    is_broken = True
                    break
                if left_zone and sub_b.low <= zone_high:
                    retest_count += 1
                    left_zone = False
                elif sub_b.low > zone_high + (atr_val * 0.25):
                    left_zone = True

            last_demand_idx = i
            if not is_broken and retest_count <= MAX_ZONE_RETESTS:
                demand_zones.append({
                    "type": "DEMAND",
                    "pattern": pattern_type,
                    "timeframe": timeframe_label,
                    "label": f"Demand {timeframe_label} ({pattern_type})",
                    "zone_high": round(zone_high, 2),
                    "zone_low": round(zone_low, 2),
                    "zone_mid": round((zone_high + zone_low) / 2.0, 2),
                    "base_candles": len(base_bars),
                    "created_time": base_start_bar.open_time.isoformat() if hasattr(base_start_bar.open_time, "isoformat") else str(base_start_bar.open_time),
                    "is_broken": False,
                    "tested": retest_count > 0,
                    "retest_count": retest_count,
                    "freshness": "FRESH" if retest_count == 0 else ("TESTED" if retest_count <= 2 else "AGED"),
                    "confluence": 2 if timeframe_label == "1H" else 1,
                })

        # 2. Supply Zone Evaluation
        elif is_bear_impulse and leg2.close < raw_low and (i - last_supply_idx) >= 3:
            pattern_type = "RBD" if leg1_body > 0 else "DBD"
            zone_high, zone_low = clamp_zone_size(raw_high, raw_low, atr_val, max_atr_mult=1.5, zone_type="SUPPLY")

            # Sequential Lifecycle Check across ALL bars after departure
            is_broken = False
            retest_count = 0
            left_zone = True  # leg2 closed below raw_low <= zone_low
            for sub_b in bars[i + 1:]:
                # Close above Supply ceiling permanently invalidates the zone [XAU-RULE-15]
                if sub_b.close > zone_high:
                    is_broken = True
                    break
                if left_zone and sub_b.high >= zone_low:
                    retest_count += 1
                    left_zone = False
                elif sub_b.high < zone_low - (atr_val * 0.25):
                    left_zone = True

            last_supply_idx = i
            if not is_broken and retest_count <= MAX_ZONE_RETESTS:
                supply_zones.append({
                    "type": "SUPPLY",
                    "pattern": pattern_type,
                    "timeframe": timeframe_label,
                    "label": f"Supply {timeframe_label} ({pattern_type})",
                    "zone_high": round(zone_high, 2),
                    "zone_low": round(zone_low, 2),
                    "zone_mid": round((zone_high + zone_low) / 2.0, 2),
                    "base_candles": len(base_bars),
                    "created_time": base_start_bar.open_time.isoformat() if hasattr(base_start_bar.open_time, "isoformat") else str(base_start_bar.open_time),
                    "is_broken": False,
                    "tested": retest_count > 0,
                    "retest_count": retest_count,
                    "freshness": "FRESH" if retest_count == 0 else ("TESTED" if retest_count <= 2 else "AGED"),
                    "confluence": 2 if timeframe_label == "1H" else 1,
                })

    fused_demands = combine_overlapping_zones(demand_zones, atr_val)
    fused_supplies = combine_overlapping_zones(supply_zones, atr_val)

    return {
        "demand_zones": fused_demands[-5:] if fused_demands else [],
        "supply_zones": fused_supplies[-5:] if fused_supplies else []
    }


def calculate_drop_speed(bars_5m: List[Bar], current_atr: float) -> Dict[str, Any]:
    """
    Calculates downward and upward momentum velocity across recent M5 candles
    (including the live forming candle to catch sudden flash crashes or rocket spikes immediately).
    """
    if not bars_5m or len(bars_5m) < 3:
        return {
            "is_severe_waterfall": False,
            "drop_distance": 0.0,
            "drop_speed_atr": 0.0,
            "bearish_streak": 0,
            "surge_distance": 0.0,
            "surge_speed_atr": 0.0,
            "is_severe_surge": False
        }

    recent_3 = bars_5m[-3:]
    drop_dist = recent_3[0].open - recent_3[-1].close
    drop_speed_atr = (drop_dist / current_atr) if current_atr > 0 else 0.0

    bearish_streak = sum(1 for b in recent_3 if b.close < b.open)
    is_severe_waterfall = (drop_speed_atr >= 2.5) or (bearish_streak == 3 and drop_speed_atr >= 1.8)

    surge_dist = recent_3[-1].close - recent_3[0].open
    surge_speed_atr = (surge_dist / current_atr) if current_atr > 0 else 0.0
    bullish_streak = sum(1 for b in recent_3 if b.close > b.open)
    is_severe_surge = (surge_speed_atr >= 2.5) or (bullish_streak == 3 and surge_speed_atr >= 1.8)

    return {
        "is_severe_waterfall": is_severe_waterfall,
        "drop_distance": round(drop_dist, 2),
        "drop_speed_atr": round(drop_speed_atr, 2),
        "bearish_streak": bearish_streak,
        "is_severe_surge": is_severe_surge,
        "surge_distance": round(surge_dist, 2),
        "surge_speed_atr": round(surge_speed_atr, 2)
    }


def _select_confirmed_and_live_bar(bars: List[Bar]) -> Tuple[Optional[Bar], Optional[Bar]]:
    """
    Separates the latest CLOSED (confirmed) candle for reliable entry triggers
    from the LIVE (unconfirmed) candle used for real-time danger cancellation.
    """
    if not bars:
        return None, None
    live_bar = bars[-1]
    if live_bar.is_confirmed:
        return live_bar, live_bar
    confirmed_bar = bars[-2] if len(bars) >= 2 else None
    return confirmed_bar, live_bar


def _evaluate_rejection_and_danger(
    bars_5m: List[Bar],
    bars_15m: List[Bar],
    zone_mid: float,
    current_atr: float,
    side: str  # "BUY" or "SELL"
) -> Dict[str, Any]:
    """
    Evaluates:
    - Entry Rejection Confirmation strictly on CLOSED candles (`confirmed_5m`, `confirmed_15m`)
      to eliminate fake intra-bar wick traps.
    - Violent Candle / Volatility Spike Danger across BOTH live and closed candles
      for immediate protection.
    """
    conf_5m, live_5m = _select_confirmed_and_live_bar(bars_5m)
    conf_15m, live_15m = _select_confirmed_and_live_bar(bars_15m)
    speed_metrics = calculate_drop_speed(bars_5m, current_atr)

    has_5m_rejection = False
    rejection_5m_ratio = 0.0
    if conf_5m:
        r5 = max(conf_5m.high - conf_5m.low, 0.001)
        if side == "BUY":
            wick5 = min(conf_5m.open, conf_5m.close) - conf_5m.low
            rejection_5m_ratio = wick5 / r5
            has_5m_rejection = (rejection_5m_ratio >= 0.25) or (conf_5m.close > conf_5m.open and conf_5m.close >= zone_mid)
        else:
            wick5 = conf_5m.high - max(conf_5m.open, conf_5m.close)
            rejection_5m_ratio = wick5 / r5
            has_5m_rejection = (rejection_5m_ratio >= 0.25) or (conf_5m.close < conf_5m.open and conf_5m.close <= zone_mid)

    has_15m_rejection = False
    rejection_15m_ratio = 0.0
    if conf_15m:
        r15 = max(conf_15m.high - conf_15m.low, 0.001)
        if side == "BUY":
            wick15 = min(conf_15m.open, conf_15m.close) - conf_15m.low
            rejection_15m_ratio = wick15 / r15
            has_15m_rejection = (rejection_15m_ratio >= 0.25) or (conf_15m.close > conf_15m.open and conf_15m.close >= zone_mid)
        else:
            wick15 = conf_15m.high - max(conf_15m.open, conf_15m.close)
            rejection_15m_ratio = wick15 / r15
            has_15m_rejection = (rejection_15m_ratio >= 0.25) or (conf_15m.close < conf_15m.open and conf_15m.close <= zone_mid)

    def _is_violent_bar(b: Optional[Bar], atr_mult: float, body_ratio_min: float) -> bool:
        if not b:
            return False
        rng = max(b.high - b.low, 0.001)
        body = b.close - b.open
        if side == "BUY":
            return (body < 0) and (abs(body) >= body_ratio_min * rng) and (rng >= atr_mult * current_atr)
        return (body > 0) and (abs(body) >= body_ratio_min * rng) and (rng >= atr_mult * current_atr)

    violent_5m = _is_violent_bar(live_5m, 1.0, 0.75) or _is_violent_bar(conf_5m, 1.0, 0.75)
    violent_15m = _is_violent_bar(live_15m, 1.8, 0.70) or _is_violent_bar(conf_15m, 1.8, 0.70)

    # Check live volatility spike against direction
    live_bar_ref = live_5m or live_15m
    vol_spike = False
    if live_bar_ref:
        sp_flag, _ = is_volatility_spike(live_bar_ref.high - live_bar_ref.low, current_atr, spike_multiplier=2.0)
        if sp_flag:
            if side == "BUY" and live_bar_ref.close < live_bar_ref.open:
                vol_spike = True
            elif side == "SELL" and live_bar_ref.close > live_bar_ref.open:
                vol_spike = True

    if side == "BUY":
        is_danger = violent_15m or violent_5m or speed_metrics["is_severe_waterfall"] or vol_spike
    else:
        is_danger = violent_15m or violent_5m or speed_metrics["is_severe_surge"] or vol_spike

    has_rejection = (has_5m_rejection or has_15m_rejection) and not is_danger
    trigger_tf = "M5" if has_5m_rejection else ("15m" if has_15m_rejection else "NONE")

    return {
        "has_rejection": has_rejection,
        "has_5m_rejection": has_5m_rejection,
        "has_15m_rejection": has_15m_rejection,
        "rejection_5m_ratio": rejection_5m_ratio,
        "rejection_15m_ratio": rejection_15m_ratio,
        "is_danger": is_danger,
        "vol_spike": vol_spike,
        "speed_metrics": speed_metrics,
        "trigger_tf": trigger_tf
    }


def scan_gold_setup() -> Dict[str, Any]:
    """
    Evaluates actionable Gold (XAU/USD) trade setup based on:
    1. Multi-Timeframe Demand & Supply Zones (DBR, RBR, RBD, DBD) + Active S/R
    2. Direction-Aware Multi-Swing Fibonacci Confluence (Upswing Buy Discount vs Downswing Sell Premium)
    3. H1 + M15 Trend Context Filter & Confirmed-Bar M5/15m Rejection
    4. Trading Session & London x New York Overlap status
    5. Spread-aware TP & SL calculation + Unified Headroom Guards
    """
    adapter = MT5DataAdapter()
    adapter._ensure_connected()
    symbol = "XAUUSD"
    resolved = adapter._resolve_symbol(symbol) or "XAUUSDc"

    bars_5m = adapter.get_bars(resolved, TimeFrame.M5, limit=120) or []
    bars_15m = adapter.get_bars(resolved, TimeFrame.M15, limit=200) or []
    bars_h1 = adapter.get_bars(resolved, TimeFrame.H1, limit=120) or []
    bars_day = adapter.get_bars(resolved, TimeFrame.DAY, limit=100) or []

    current_price = 2650.0
    if bars_5m:
        current_price = bars_5m[-1].close
    elif bars_15m:
        current_price = bars_15m[-1].close

    quote = adapter.get_latest_quote(resolved) or {}
    live_spread = float(quote.get("spread") or 0.20)
    if live_spread < 0:
        live_spread = 0.20

    atr_vals = calculate_atr(bars_15m, period=14) if len(bars_15m) >= 15 else []
    current_atr = float(atr_vals[-1]["value"]) if atr_vals else 4.50

    # Trend Context: M15 (EMA15 vs MA50) + H1 (Price vs EMA50)
    ema15_list = calculate_ema(bars_15m, 15) if len(bars_15m) >= 15 else []
    ma50_list = calculate_sma(bars_15m, 50) if len(bars_15m) >= 50 else []
    h1_ema50_list = calculate_ema(bars_h1, 50) if len(bars_h1) >= 50 else []

    ema15_val = ema15_list[-1]["value"] if ema15_list else None
    ma50_val = ma50_list[-1]["value"] if ma50_list else None
    h1_ema50_val = h1_ema50_list[-1]["value"] if h1_ema50_list else None

    m15_trend = (
        "BULLISH" if (ema15_val and ma50_val and ema15_val > ma50_val)
        else ("BEARISH" if (ema15_val and ma50_val and ema15_val < ma50_val) else "NEUTRAL")
    )
    h1_trend = (
        "BULLISH" if (h1_ema50_val and current_price > h1_ema50_val + current_atr * 0.5)
        else ("BEARISH" if (h1_ema50_val and current_price < h1_ema50_val - current_atr * 0.5) else "NEUTRAL")
    )
    # Strong macro trend occurs when both H1 and M15 agree
    strong_bull_trend = (h1_trend == "BULLISH" and m15_trend == "BULLISH")
    strong_bear_trend = (h1_trend == "BEARISH" and m15_trend == "BEARISH")

    # Zero-look-ahead Swing Market Structure (HH/HL/LH/LL + live BOS/CHoCH)
    m15_structure = analyze_market_structure(bars_15m, n_fractal=3) if bars_15m else {
        "bias": "NEUTRAL", "swing_bias": "NEUTRAL", "pattern": "INSUFFICIENT",
        "live_break": "NONE", "last_sh": None, "last_sl": None,
    }
    h1_structure = analyze_market_structure(bars_h1, n_fractal=3) if bars_h1 else {
        "bias": "NEUTRAL", "swing_bias": "NEUTRAL", "pattern": "INSUFFICIENT",
        "live_break": "NONE", "last_sh": None, "last_sl": None,
    }
    m15_choch_bear = (m15_structure.get("live_break") == "CHOCH_BEAR")
    m15_choch_bull = (m15_structure.get("live_break") == "CHOCH_BULL")

    # 1. Session Detection
    eval_time = bars_15m[-1].close_time if (bars_15m and hasattr(bars_15m[-1], "close_time")) else None
    session_info = detect_trading_session(eval_time)

    # 2. Support / Resistance & Role Reversal (M15 + H1 + Daily Structural Levels)
    sr_zones = build_sr_zones("XAUUSD", bars_15m, n_fractal=4, atr_multiplier=0.4) if bars_15m else []
    h1_sr_zones = build_sr_zones("XAUUSD", bars_h1, n_fractal=3, atr_multiplier=0.4) if len(bars_h1) >= 20 else []
    day_sr_zones = build_sr_zones("XAUUSD", bars_day, n_fractal=3, atr_multiplier=0.35) if len(bars_day) >= 25 else []
    role_reversals = [z for z in sr_zones if z.is_role_reversed and z.is_active]
    h1_macro_role_reversals = [z for z in (h1_sr_zones + day_sr_zones) if z.is_role_reversed and z.is_active]

    m15_supports = [
        {
            "type": "DEMAND",
            "pattern": "M15_SUPPORT",
            "timeframe": "15m",
            "label": f"M15 Support [Touches {z.touch_count}]",
            "zone_high": round(z.price_high, 2),
            "zone_low": round(z.price_low, 2),
            "zone_mid": round(z.price_mid, 2),
            "created_time": str(z.confirmed_at or datetime.now(timezone.utc)),
            "is_broken": z.is_broken,
            "tested": z.touch_count > 0,
            "retest_count": z.touch_count,
            "freshness": z.freshness,
            "confluence": 1,
        }
        for z in sr_zones if z.zone_type == "SUPPORT" and not z.is_broken and z.is_active and z.touch_count <= MAX_ZONE_RETESTS
    ]
    m15_resistances = [
        {
            "type": "SUPPLY",
            "pattern": "M15_RESISTANCE",
            "timeframe": "15m",
            "label": f"M15 Resistance [Touches {z.touch_count}]",
            "zone_high": round(z.price_high, 2),
            "zone_low": round(z.price_low, 2),
            "zone_mid": round(z.price_mid, 2),
            "created_time": str(z.confirmed_at or datetime.now(timezone.utc)),
            "is_broken": z.is_broken,
            "tested": z.touch_count > 0,
            "retest_count": z.touch_count,
            "freshness": z.freshness,
            "confluence": 1,
        }
        for z in sr_zones if z.zone_type == "RESISTANCE" and not z.is_broken and z.is_active and z.touch_count <= MAX_ZONE_RETESTS
    ]

    # 3. Demand & Supply Zones (Multi-Timeframe M15 + H1 with Edge-Anchored Clamping & Fusion)
    ds_zones_15m = detect_demand_supply_zones(bars_15m, min_bars=15, timeframe_label="15m", atr_val=current_atr) if bars_15m else {"demand_zones": [], "supply_zones": []}
    ds_zones_h1 = detect_demand_supply_zones(bars_h1, min_bars=15, timeframe_label="1H", atr_val=current_atr * 2.0) if bars_h1 else {"demand_zones": [], "supply_zones": []}

    all_demands = combine_overlapping_zones(ds_zones_15m["demand_zones"] + ds_zones_h1["demand_zones"] + m15_supports, current_atr)
    all_supplies = combine_overlapping_zones(ds_zones_15m["supply_zones"] + ds_zones_h1["supply_zones"] + m15_resistances, current_atr)

    demands = sorted(all_demands, key=lambda d: abs(current_price - d["zone_high"]))
    supplies = sorted(all_supplies, key=lambda s: abs(current_price - s["zone_low"]))

    # 4. Direction-Aware Multi-Swing Fibonacci Engine (PineScript V3 ZigZag: pivot_legs=10, min_rev=1.0%, confirmed swings only)
    zz_pivots = detect_zigzag_pivots(bars_15m, pivot_legs=10, min_deviation_pct=1.0) if len(bars_15m) >= 25 else []
    if len(zz_pivots) < 2 and len(bars_15m) >= 15:
        zz_pivots = detect_zigzag_pivots(bars_15m, pivot_legs=6, min_deviation_pct=0.7)

    major_fibo_up: Dict[str, Any] = {}
    minor_fibo_up: Dict[str, Any] = {}
    major_fibo_down: Dict[str, Any] = {}
    minor_fibo_down: Dict[str, Any] = {}
    fibo_history: List[Dict[str, Any]] = []
    swing_direction = "UP"

    if len(zz_pivots) >= 2:
        # Build confirmed historical swings (newest first, up to last 3 swings) so AI Trader can cross-check prior Fibos
        for idx in range(len(zz_pivots) - 1, 0, -1):
            p_end = zz_pivots[idx]
            p_start = zz_pivots[idx - 1]
            if p_end.pivot_type == 1 and p_start.pivot_type == -1 and (p_end.price - p_start.price) >= (current_atr * 2.0):
                leg_fibo = calculate_fibonacci_retracement(p_end.price, p_start.price, label=f"ConfirmedSwing#{len(fibo_history)+1}", direction="UP")
                fibo_history.append(leg_fibo)
                if not minor_fibo_up:
                    minor_fibo_up = calculate_fibonacci_retracement(p_end.price, p_start.price, label="Minor", direction="UP")
            elif p_end.pivot_type == -1 and p_start.pivot_type == 1 and (p_start.price - p_end.price) >= (current_atr * 2.0):
                leg_fibo = calculate_fibonacci_retracement(p_start.price, p_end.price, label=f"ConfirmedSwing#{len(fibo_history)+1}", direction="DOWN")
                fibo_history.append(leg_fibo)
                if not minor_fibo_down:
                    minor_fibo_down = calculate_fibonacci_retracement(p_start.price, p_end.price, label="Minor", direction="DOWN")
            if len(fibo_history) >= 3:
                break

        # Active direction follows the latest confirmed swing leg (no unconfirmed projected repaint)
        last_p = zz_pivots[-1]
        swing_direction = "UP" if last_p.pivot_type == 1 else "DOWN"

        # Major Swing (Macro High & Low with chronological direction)
        high_pivots = [p for p in zz_pivots if p.pivot_type == 1]
        low_pivots = [p for p in zz_pivots if p.pivot_type == -1]
        if high_pivots and low_pivots:
            maj_h_piv = max(high_pivots, key=lambda p: p.price)
            maj_l_piv = min(low_pivots, key=lambda p: p.price)
            if (maj_h_piv.price - maj_l_piv.price) >= (current_atr * 4.0):
                major_fibo_up = calculate_fibonacci_retracement(maj_h_piv.price, maj_l_piv.price, label="Major", direction="UP")
                major_fibo_down = calculate_fibonacci_retracement(maj_h_piv.price, maj_l_piv.price, label="Major", direction="DOWN")

    if not major_fibo_up:
        major_fibo_up = minor_fibo_up
    if not major_fibo_down:
        major_fibo_down = minor_fibo_down

    # Per-zone Fibonacci Confluence annotation (strictly directional & per-zone, never global!)
    double_confluence_active = False

    for d in demands:
        maj_c = check_fibo_confluence(d["zone_high"], d["zone_low"], major_fibo_up) if major_fibo_up else {"has_confluence": False, "has_ok_fibo": False, "fibo_tier": "NONE"}
        min_c = check_fibo_confluence(d["zone_high"], d["zone_low"], minor_fibo_up) if minor_fibo_up else {"has_confluence": False, "has_ok_fibo": False, "fibo_tier": "NONE"}
        if maj_c.get("has_confluence") and min_c.get("has_confluence") and major_fibo_up != minor_fibo_up:
            conf = dict(min_c)
            conf["double_confluence"] = True
            conf["reason"] = "⭐⭐ Double Confluence: ซ้อนทับทั้ง Major & Minor Golden Zone (Buy Discount)!"
            double_confluence_active = True
        elif min_c.get("has_confluence"):
            conf = dict(min_c)
            conf["double_confluence"] = False
        elif maj_c.get("has_confluence"):
            conf = dict(maj_c)
            conf["double_confluence"] = False
        elif min_c.get("has_ok_fibo"):
            conf = dict(min_c)
            conf["double_confluence"] = False
        elif maj_c.get("has_ok_fibo"):
            conf = dict(maj_c)
            conf["double_confluence"] = False
        else:
            conf = dict(min_c if minor_fibo_up else maj_c)
            conf["double_confluence"] = False
        d["fibo_confluence"] = conf
        rr_tol = current_atr * 0.25
        d["is_h1_role_reversal"] = any(
            rr.zone_type == "RESISTANCE"
            and max(d["zone_low"], rr.price_low - rr_tol) <= min(d["zone_high"], rr.price_high + rr_tol)
            for rr in h1_macro_role_reversals
        )

    for s in supplies:
        maj_c = check_fibo_confluence(s["zone_high"], s["zone_low"], major_fibo_down) if major_fibo_down else {"has_confluence": False, "has_ok_fibo": False, "fibo_tier": "NONE"}
        min_c = check_fibo_confluence(s["zone_high"], s["zone_low"], minor_fibo_down) if minor_fibo_down else {"has_confluence": False, "has_ok_fibo": False, "fibo_tier": "NONE"}
        if maj_c.get("has_confluence") and min_c.get("has_confluence") and major_fibo_down != minor_fibo_down:
            conf = dict(min_c)
            conf["double_confluence"] = True
            conf["reason"] = "⭐⭐ Double Confluence: ซ้อนทับทั้ง Major & Minor Golden Zone (Sell Premium)!"
            double_confluence_active = True
        elif min_c.get("has_confluence"):
            conf = dict(min_c)
            conf["double_confluence"] = False
        elif maj_c.get("has_confluence"):
            conf = dict(maj_c)
            conf["double_confluence"] = False
        elif min_c.get("has_ok_fibo"):
            conf = dict(min_c)
            conf["double_confluence"] = False
        elif maj_c.get("has_ok_fibo"):
            conf = dict(maj_c)
            conf["double_confluence"] = False
        else:
            conf = dict(min_c if minor_fibo_down else maj_c)
            conf["double_confluence"] = False
        s["fibo_confluence"] = conf
        rr_tol = current_atr * 0.25
        s["is_h1_role_reversal"] = any(
            rr.zone_type == "SUPPORT"
            and max(s["zone_low"], rr.price_low - rr_tol) <= min(s["zone_high"], rr.price_high + rr_tol)
            for rr in h1_macro_role_reversals
        )

    best_fibo_buy = minor_fibo_up or major_fibo_up
    best_fibo_sell = minor_fibo_down or major_fibo_down
    best_fibo = best_fibo_buy if swing_direction == "UP" else (best_fibo_sell or best_fibo_buy)
    major_fibo = major_fibo_up if swing_direction == "UP" else (major_fibo_down or major_fibo_up)
    minor_fibo = minor_fibo_up if swing_direction == "UP" else (minor_fibo_down or minor_fibo_up)

    # 5. Helper calculations for Headroom Guards (including Daily S/R obstacles)
    def _calc_buy_headroom(ref_price: float) -> Tuple[float, Optional[Dict[str, Any]]]:
        overhead_candidates = [s for s in supplies if s["zone_low"] > ref_price]
        for dz in day_sr_zones:
            if dz.zone_type == "RESISTANCE" and not dz.is_broken and dz.price_low > ref_price:
                overhead_candidates.append({
                    "zone_low": round(dz.price_low, 2),
                    "zone_high": round(dz.price_high, 2),
                    "label": "Daily Resistance"
                })
        overhead_candidates.sort(key=lambda x: x["zone_low"])
        if overhead_candidates:
            nearest_ov = overhead_candidates[0]
            return (nearest_ov["zone_low"] - ref_price), nearest_ov
        return 999.0, None

    def _calc_sell_headroom(ref_price: float) -> Tuple[float, float]:
        underneath_demands = [d for d in demands if d["zone_high"] < ref_price]
        for dz in day_sr_zones:
            if dz.zone_type == "SUPPORT" and not dz.is_broken and dz.price_high < ref_price:
                underneath_demands.append({
                    "zone_high": round(dz.price_high, 2),
                    "zone_low": round(dz.price_low, 2),
                    "label": "Daily Support"
                })
        underneath_demands.sort(key=lambda x: ref_price - x["zone_high"])
        nearest_un = underneath_demands[0] if underneath_demands else None
        low_of_day = min([b.low for b in bars_15m[-32:]]) if len(bars_15m) >= 32 else (ref_price - 15.0)
        # Only treat low_of_day as floor if it lies below ref_price
        floor_candidates = []
        if nearest_un:
            floor_candidates.append(nearest_un["zone_high"])
        if low_of_day < ref_price:
            floor_candidates.append(low_of_day)
        if not floor_candidates:
            return 999.0, 0.0
        effective_floor = max(floor_candidates)
        return (ref_price - effective_floor), round(effective_floor, 2)

    # 6. Signal Determination
    setup_type = "WAITING_FOR_ZONE"
    direction = "NEUTRAL"
    order_execution_mode = "MARKET"
    setup_reason = "ราคากำลังเคลื่อนไหวอยู่ระหว่างโซน รอการย่อทดสอบ Demand หรือเด้งแตะ Supply"
    target_entry = current_price
    target_sl = current_price - (current_atr * 1.5)
    target_tp = current_price + (current_atr * 2.5)
    rr_ratio = 0.0
    risk_usd = 0.0
    reward_usd = 0.0
    pullback_entry_recommended = None
    trigger_tf = "NONE"
    m5_rejection_detected = False

    nearest_demand = demands[0] if demands else None
    nearest_supply = supplies[0] if supplies else None
    is_asian_session = (session_info.get("liquidity_status") == "LOW_MODERATE") or (session_info.get("bkk_hour", 12) in range(6, 15))

    # A. Demand Proximity Evaluation (BUY)
    is_touching_demand = (
        nearest_demand is not None
        and (current_price <= nearest_demand["zone_high"] + (current_atr * 0.35))
        and (current_price >= nearest_demand["zone_low"] - (current_atr * 0.50))
    )
    if is_touching_demand and nearest_demand is not None:
        trig = _evaluate_rejection_and_danger(bars_5m, bars_15m, nearest_demand["zone_mid"], current_atr, side="BUY")
        is_falling_knife = trig["is_danger"]
        has_rejection = trig["has_rejection"]
        m5_rejection_detected = trig["has_5m_rejection"]
        trigger_tf = trig["trigger_tf"]
        drop_metrics = trig["speed_metrics"]

        headroom, nearest_overhead = _calc_buy_headroom(current_price)
        is_high_quality_zone = (
            "1H" in nearest_demand.get("timeframe", "")
            or nearest_demand.get("fibo_confluence", {}).get("has_confluence", False)
            or nearest_demand.get("confluence", 1) >= 2
        )
        counter_trend_blocked = strong_bear_trend and not is_high_quality_zone

        raw_sl = nearest_demand["zone_low"] - (current_atr * 0.75)

        if is_falling_knife:
            setup_type = "REJECTED_FALLING_KNIFE"
            direction = "NEUTRAL"
            target_entry = current_price
            target_sl = raw_sl
            target_tp = current_price + (current_atr * 2.0)
            risk_usd = target_entry - target_sl
            reward_usd = target_tp - target_entry
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0
            waterfall_desc = f" (Waterfall Drop -{drop_metrics['drop_distance']:.2f}$ / {drop_metrics['drop_speed_atr']:.1f}x ATR)" if drop_metrics["is_severe_waterfall"] else ""
            setup_reason = f"⚠️ ปฏิเสธ BUY ที่ Demand: แท่งเทียนกำลังทิ้งตัวรุนแรง{waterfall_desc} บังคับรอแท่งปิดยืนยันการหยุดไหลก่อน"
        elif headroom < (current_atr * 1.0):
            setup_type = "REJECTED_NEAR_RESISTANCE"
            direction = "NEUTRAL"
            target_entry = current_price
            target_sl = raw_sl
            target_tp = current_price + (current_atr * 2.0)
            risk_usd = target_entry - target_sl
            reward_usd = target_tp - target_entry
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0
            ov_px = nearest_overhead["zone_low"] if nearest_overhead else (current_price + headroom)
            setup_reason = f"⚠️ ปฏิเสธ BUY: ราคาใกล้แนวต้าน ({ov_px:.2f}) มากเกินไป (Headroom {headroom:.2f} < 1.0x ATR) ห้ามซื้อชิดแนวต้าน"
        elif counter_trend_blocked and not has_rejection:
            setup_type = "WAITING_FOR_REJECTION"
            direction = "NEUTRAL"
            target_entry = current_price
            target_sl = raw_sl
            target_tp = current_price + (current_atr * 2.0)
            risk_usd = target_entry - target_sl
            reward_usd = target_tp - target_entry
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0
            setup_reason = "⚠️ เทรนด์หลัก H1+M15 เป็นขาลงชัดเจน: งดวาง Blind Buy Limit บนโซนย่อย M15 ต้องรอแท่งปิดยืนยันการกลับตัวเท่านั้น"
        else:
            above_supplies = [s for s in supplies if s["zone_low"] > current_price]
            if above_supplies:
                target_tp = above_supplies[0]["zone_low"] - (current_atr * 0.35)
            else:
                target_tp = current_price + (current_atr * 2.0)

            # Realistic Intraday TP Cap ($16 USD max intraday swing unless closer obstacle)
            calculated_risk = max(current_price - (nearest_demand["zone_low"] - (current_atr * 0.35)), 3.0)
            ideal_realistic_tp = current_price + (calculated_risk * 2.0)
            if target_tp > ideal_realistic_tp and (target_tp - current_price) > 16.0:
                target_tp = min(target_tp, current_price + 16.0)

            is_chasing_above_zone = (current_price > nearest_demand["zone_high"] + (current_atr * 0.40))
            sl_distance = current_price - raw_sl
            risk_usd = sl_distance
            reward_usd = target_tp - current_price
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0

            # Compute Smart Buy Limit candidate inside zone (OTE 65% / Fibo 38.2-50% target if aligned, else zone_mid)
            zone_conf = nearest_demand.get("fibo_confluence", {})
            fibo_cand = (
                zone_conf.get("fibo_650")
                if zone_conf.get("has_confluence")
                else zone_conf.get("fibo_target_level")
            )
            has_limit_fibo_or_rr = bool(
                zone_conf.get("has_ok_fibo")
                or zone_conf.get("has_confluence")
                or nearest_demand.get("is_h1_role_reversal")
            )
            limit_entry_candidate = fibo_cand or nearest_demand.get("zone_mid") or (nearest_demand["zone_low"] + current_atr * 0.25)
            limit_entry = min(max(limit_entry_candidate, nearest_demand["zone_low"]), nearest_demand["zone_high"])
            # Ensure BUY LIMIT is strictly below current price; if current_price is already deep inside zone, step slightly below current_price
            if limit_entry >= current_price:
                limit_entry = round(max(nearest_demand["zone_low"], current_price - max(live_spread, 0.25)), 2)

            limit_headroom, _ = _calc_buy_headroom(limit_entry)
            limit_sl_dist = limit_entry - raw_sl
            limit_rew_dist = target_tp - limit_entry
            limit_rr = (limit_rew_dist / limit_sl_dist) if limit_sl_dist > 0 else 0.0
            can_use_limit = (
                has_limit_fibo_or_rr
                and limit_entry < current_price
                and MIN_GOLD_SL_USD <= limit_sl_dist <= MAX_GOLD_SL_USD
                and limit_rr >= MIN_GOLD_RR_RATIO
                and limit_headroom >= (current_atr * 1.0)
                and not strong_bear_trend
                and not m15_choch_bear
            )

            if has_rejection and not is_chasing_above_zone and not is_asian_session and 0 < sl_distance <= MAX_GOLD_SL_USD and rr_ratio >= MIN_GOLD_RR_RATIO:
                target_entry = current_price
                target_sl = raw_sl
                order_execution_mode = "MARKET"
                setup_type = "BUY_DEMAND_ZONE"
                direction = "BUY"
                best_fibo = best_fibo_buy or best_fibo
                setup_reason = (
                    f"ราคาแตะโซน Demand ({nearest_demand['pattern']}) ชิดฐานที่ {nearest_demand['zone_low']} - {nearest_demand['zone_high']} "
                    f"ยืนยันด้วยแท่งปิด {trigger_tf} พร้อม R:R {rr_ratio:.2f} (Headroom ปลอดภัย {headroom:.2f})"
                )
            elif not has_rejection and can_use_limit:
                target_entry = round(limit_entry, 2)
                target_sl = round(raw_sl, 2)
                order_execution_mode = "LIMIT"
                setup_type = "ACTIONABLE_BUY_LIMIT"
                direction = "BUY"
                risk_usd = limit_sl_dist
                reward_usd = limit_rew_dist
                rr_ratio = limit_rr
                best_fibo = best_fibo_buy or best_fibo
                setup_reason = (
                    f"🎯 แนะนำ Buy Limit ดักย่อที่ Fibo 65% OTE / Demand Base (${target_entry:.2f}) SL ${target_sl:.2f} (R:R {rr_ratio:.2f}) "
                    f"[Option 2: Dynamic Limit Pre-placement - [XAU-RULE-23]]"
                )
            elif has_rejection and (is_chasing_above_zone or is_asian_session) and can_use_limit:
                target_entry = round(limit_entry, 2)
                target_sl = round(raw_sl, 2)
                order_execution_mode = "LIMIT"
                setup_type = "ACTIONABLE_BUY_LIMIT"
                direction = "BUY"
                risk_usd = limit_sl_dist
                reward_usd = limit_rew_dist
                rr_ratio = limit_rr
                best_fibo = best_fibo_buy or best_fibo
                setup_reason = (
                    f"🎯 แนะนำ Buy Limit ดักย่อที่ Fibo 65% OTE / Demand Base (${target_entry:.2f}) SL ${target_sl:.2f} (R:R {rr_ratio:.2f}) "
                    f"[กรองตลาดเอเชีย/ไม่ไล่ราคา]"
                )
            elif not has_rejection:
                setup_type = "WAITING_FOR_REJECTION"
                direction = "NEUTRAL"
                target_entry = current_price
                target_sl = raw_sl
                risk_usd = sl_distance
                reward_usd = reward_usd
                setup_reason = (
                    f"ราคาแตะ Demand Base ({nearest_demand['pattern']}) แล้วที่ ${current_price:.2f} "
                    f"กำลังรอแท่งเทียน M5/15m ปิดเกิด Rejection Wick ยืนยัน (หางล่าง M5: {trig['rejection_5m_ratio']*100:.1f}%, 15m: {trig['rejection_15m_ratio']*100:.1f}% < 25%) "
                    f"เพื่อป้องกันการรับมีดตก [XAU-RULE-06]"
                )
            elif sl_distance > MAX_GOLD_SL_USD:
                setup_type = "REJECTED_SL_TOO_WIDE"
                direction = "NEUTRAL"
                target_entry = current_price
                target_sl = raw_sl
                setup_reason = (
                    f"⚠️ ปฏิเสธ BUY: ระยะ Stop Loss กว้างเกินเกณฑ์ (${sl_distance:.2f} > ${MAX_GOLD_SL_USD:.2f}) "
                    f"เสี่ยงเกินขนาดสำหรับ Intraday Scalp รอราคาย่อตัวลึกเข้าเนื้อ Demand Zone (${nearest_demand['zone_low']:.2f} - ${nearest_demand['zone_high']:.2f})"
                )
            else:
                setup_type = "REJECTED_POOR_RR"
                direction = "NEUTRAL"
                target_entry = current_price
                target_sl = raw_sl
                pullback_entry = min(nearest_demand["zone_high"], target_tp - (risk_usd * MIN_GOLD_RR_RATIO))
                pullback_entry_recommended = round(pullback_entry, 2)
                setup_reason = (
                    f"⚠️ ปฏิเสธ BUY: Risk:Reward ต่ำเกินไป (R:R {rr_ratio:.2f} < {MIN_GOLD_RR_RATIO:.2f} | เสี่ยง ${risk_usd:.2f} เพื่อกำไร ${reward_usd:.2f}) "
                    f"ห้ามไล่ราคา ควรรอย่อ Pullback เข้าเนื้อ Demand Zone ({nearest_demand['zone_low']:.2f} - {nearest_demand['zone_high']:.2f})"
                )

    # B. Supply Proximity Evaluation (SELL)
    is_touching_supply = (
        nearest_supply is not None
        and (current_price >= nearest_supply["zone_low"] - (current_atr * 0.35))
        and (current_price <= nearest_supply["zone_high"] + (current_atr * 0.50))
    )
    if is_touching_supply and nearest_supply is not None and direction == "NEUTRAL" and not is_touching_demand:
        trig = _evaluate_rejection_and_danger(bars_5m, bars_15m, nearest_supply["zone_mid"], current_atr, side="SELL")
        is_rocket_candle = trig["is_danger"]
        has_rejection = trig["has_rejection"]
        m5_rejection_detected = trig["has_5m_rejection"]
        trigger_tf = trig["trigger_tf"]

        effective_down_headroom, effective_support_floor = _calc_sell_headroom(current_price)
        min_required_headroom = current_atr * MIN_HEADROOM_ATR_MULT

        is_high_quality_zone = (
            "1H" in nearest_supply.get("timeframe", "")
            or nearest_supply.get("fibo_confluence", {}).get("has_confluence", False)
            or nearest_supply.get("confluence", 1) >= 2
        )
        counter_trend_blocked = strong_bull_trend and not is_high_quality_zone

        # Spread-aware SELL SL: SELL closes on Ask price (Bid + live_spread)
        raw_sl = nearest_supply["zone_high"] + (current_atr * 0.75) + live_spread

        if is_rocket_candle:
            setup_type = "REJECTED_ROCKET_SURGE"
            direction = "NEUTRAL"
            target_entry = current_price
            target_sl = raw_sl
            target_tp = current_price - (current_atr * 2.0)
            risk_usd = target_sl - target_entry
            reward_usd = target_entry - target_tp
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0
            setup_reason = "⚠️ ปฏิเสธ SELL ที่ Supply: แท่งเทียนกำลังพุ่งขึ้นรุนแรง (Rocket Surge) บังคับรอแท่งปิด Rejection Wick ยืนยันก่อน"
        elif effective_down_headroom < min_required_headroom:
            setup_type = "REJECTED_NEAR_SUPPORT_HEADROOM"
            direction = "NEUTRAL"
            target_entry = current_price
            target_sl = raw_sl
            target_tp = current_price - (current_atr * 2.0)
            risk_usd = target_sl - target_entry
            reward_usd = target_entry - target_tp
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0
            setup_reason = (
                f"⚠️ ปฏิเสธ SELL: พื้นที่ลงแคบเกินไป (Headroom {effective_down_headroom:.2f} < {min_required_headroom:.2f} [1.5x ATR]) "
                f"ราคาอยู่ชิดแนวรับ/Low วัน ({effective_support_floor:.2f}) ห้ามขายก้นเหวเด็ดขาด เสี่ยงโดนดีดสวน"
            )
        elif counter_trend_blocked and not has_rejection:
            setup_type = "WAITING_FOR_REJECTION"
            direction = "NEUTRAL"
            target_entry = current_price
            target_sl = raw_sl
            target_tp = current_price - (current_atr * 2.0)
            risk_usd = target_sl - target_entry
            reward_usd = target_entry - target_tp
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0
            setup_reason = "⚠️ เทรนด์หลัก H1+M15 เป็นขาขึ้นชัดเจน: งดวาง Blind Sell Limit บนโซนย่อย M15 ต้องรอแท่งปิดยืนยันการกลับตัวเท่านั้น"
        else:
            below_demands = [d for d in demands if d["zone_high"] < current_price]
            if below_demands:
                target_tp = below_demands[0]["zone_high"] + (current_atr * 0.35)
            else:
                target_tp = current_price - (current_atr * 2.0)

            calculated_risk = max((nearest_supply["zone_high"] + (current_atr * 0.35)) - current_price, 3.0)
            ideal_realistic_tp = current_price - (calculated_risk * 2.0)
            if target_tp < ideal_realistic_tp and (current_price - target_tp) > 16.0:
                target_tp = max(target_tp, current_price - 16.0)

            is_chasing_below_zone = (current_price < nearest_supply["zone_low"] - (current_atr * 0.40))
            sl_distance = raw_sl - current_price
            risk_usd = sl_distance
            reward_usd = current_price - target_tp
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0

            zone_conf = nearest_supply.get("fibo_confluence", {})
            fibo_cand = (
                zone_conf.get("fibo_650")
                if zone_conf.get("has_confluence")
                else zone_conf.get("fibo_target_level")
            )
            has_limit_fibo_or_rr = bool(
                zone_conf.get("has_ok_fibo")
                or zone_conf.get("has_confluence")
                or nearest_supply.get("is_h1_role_reversal")
            )
            limit_entry_candidate = fibo_cand or nearest_supply.get("zone_mid") or (nearest_supply["zone_high"] - current_atr * 0.25)
            limit_entry = max(min(limit_entry_candidate, nearest_supply["zone_high"]), nearest_supply["zone_low"])
            if limit_entry <= current_price:
                limit_entry = round(min(nearest_supply["zone_high"], current_price + max(live_spread, 0.25)), 2)

            limit_down_headroom, _ = _calc_sell_headroom(limit_entry)
            limit_sl_dist = raw_sl - limit_entry
            limit_rew_dist = limit_entry - target_tp
            limit_rr = (limit_rew_dist / limit_sl_dist) if limit_sl_dist > 0 else 0.0
            can_use_limit = (
                has_limit_fibo_or_rr
                and limit_entry > current_price
                and MIN_GOLD_SL_USD <= limit_sl_dist <= MAX_GOLD_SL_USD
                and limit_rr >= MIN_GOLD_RR_RATIO
                and limit_down_headroom >= min_required_headroom
                and not strong_bull_trend
                and not m15_choch_bull
            )

            if has_rejection and not is_chasing_below_zone and not is_asian_session and 0 < sl_distance <= MAX_GOLD_SL_USD and rr_ratio >= MIN_GOLD_RR_RATIO:
                target_entry = current_price
                target_sl = raw_sl
                order_execution_mode = "MARKET"
                setup_type = "SELL_SUPPLY_ZONE"
                direction = "SELL"
                best_fibo = best_fibo_sell or best_fibo
                setup_reason = (
                    f"ราคาแตะโซน Supply ({nearest_supply['pattern']}) ชิดฐานที่ {nearest_supply['zone_low']} - {nearest_supply['zone_high']} "
                    f"ยืนยันด้วยแท่งปิด {trigger_tf} พร้อม R:R {rr_ratio:.2f}"
                )
            elif not has_rejection and can_use_limit:
                target_entry = round(limit_entry, 2)
                target_sl = round(raw_sl, 2)
                order_execution_mode = "LIMIT"
                setup_type = "ACTIONABLE_SELL_LIMIT"
                direction = "SELL"
                risk_usd = limit_sl_dist
                reward_usd = limit_rew_dist
                rr_ratio = limit_rr
                best_fibo = best_fibo_sell or best_fibo
                setup_reason = (
                    f"🎯 แนะนำ Sell Limit ดักเด้งที่ Fibo 65% OTE / Supply Base (${target_entry:.2f}) SL ${target_sl:.2f} (R:R {rr_ratio:.2f}) "
                    f"[Option 2: Dynamic Limit Pre-placement - [XAU-RULE-23]]"
                )
            elif has_rejection and (is_chasing_below_zone or is_asian_session) and can_use_limit:
                target_entry = round(limit_entry, 2)
                target_sl = round(raw_sl, 2)
                order_execution_mode = "LIMIT"
                setup_type = "ACTIONABLE_SELL_LIMIT"
                direction = "SELL"
                risk_usd = limit_sl_dist
                reward_usd = limit_rew_dist
                rr_ratio = limit_rr
                best_fibo = best_fibo_sell or best_fibo
                setup_reason = (
                    f"🎯 แนะนำ Sell Limit ดักเด้งที่ Fibo 65% OTE / Supply Base (${target_entry:.2f}) SL ${target_sl:.2f} (R:R {rr_ratio:.2f}) "
                    f"[กรองตลาดเอเชีย/ไม่ไล่ราคา]"
                )
            elif not has_rejection:
                setup_type = "WAITING_FOR_REJECTION"
                direction = "NEUTRAL"
                target_entry = current_price
                target_sl = raw_sl
                setup_reason = (
                    f"ราคาแตะ Supply Base ({nearest_supply['pattern']}) แล้วที่ ${current_price:.2f} "
                    f"กำลังรอแท่งเทียน M5/15m ปิดเกิด Rejection Wick ยืนยัน [XAU-RULE-06]"
                )
            elif sl_distance > MAX_GOLD_SL_USD:
                setup_type = "REJECTED_SL_TOO_WIDE"
                direction = "NEUTRAL"
                target_entry = current_price
                target_sl = raw_sl
                setup_reason = (
                    f"⚠️ ปฏิเสธ SELL: ระยะ Stop Loss กว้างเกินเกณฑ์ (${sl_distance:.2f} > ${MAX_GOLD_SL_USD:.2f}) "
                    f"เสี่ยงเกินขนาดสำหรับ Intraday Scalp รอราคาเด้งทดสอบ Supply Zone (${nearest_supply['zone_low']:.2f} - ${nearest_supply['zone_high']:.2f})"
                )
            else:
                setup_type = "REJECTED_POOR_RR"
                direction = "NEUTRAL"
                target_entry = current_price
                target_sl = raw_sl
                setup_reason = (
                    f"⚠️ ปฏิเสธ SELL: Risk:Reward ต่ำเกินไป (R:R {rr_ratio:.2f} < {MIN_GOLD_RR_RATIO:.2f}) "
                    f"ห้ามไล่ราคา ควรรอเด้ง Pullback เข้าเนื้อ Supply Zone ({nearest_supply['zone_low']:.2f} - {nearest_supply['zone_high']:.2f})"
                )

    # C. Role Reversal Proximity (Fully guarded with Danger, Confirmed Rejection, Session, and Headroom checks!)
    elif role_reversals and direction == "NEUTRAL":
        closest_rr = min(role_reversals, key=lambda z: abs(z.price_mid - current_price))
        if abs(closest_rr.price_mid - current_price) <= (current_atr * 0.5):
            # Broken Resistance -> New Support (BUY Role Reversal)
            if closest_rr.zone_type == "RESISTANCE" and current_price >= closest_rr.price_low:
                trig = _evaluate_rejection_and_danger(bars_5m, bars_15m, closest_rr.price_mid, current_atr, side="BUY")
                headroom, nearest_overhead = _calc_buy_headroom(current_price)
                m5_rejection_detected = trig["has_5m_rejection"]
                trigger_tf = trig["trigger_tf"]

                target_entry = current_price
                target_sl = closest_rr.price_low - (current_atr * 0.75)
                above_supplies = [s for s in supplies if s["zone_low"] > current_price]
                target_tp = (above_supplies[0]["zone_low"] - current_atr * 0.35) if above_supplies else (current_price + current_atr * 2.0)
                target_tp = min(target_tp, current_price + 16.0)
                risk_usd = target_entry - target_sl
                reward_usd = target_tp - target_entry
                rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0

                if trig["is_danger"]:
                    setup_type = "REJECTED_FALLING_KNIFE"
                    direction = "NEUTRAL"
                    setup_reason = "⚠️ ปฏิเสธ BUY Role Reversal: แท่งเทียนทิ้งตัวรุนแรง (Falling Knife) ห้ามรับมีด"
                elif headroom < (current_atr * 1.0):
                    setup_type = "REJECTED_NEAR_RESISTANCE"
                    direction = "NEUTRAL"
                    setup_reason = f"⚠️ ปฏิเสธ BUY Role Reversal: ติดแนวต้านด้านบน (Headroom {headroom:.2f} < 1.0x ATR)"
                elif not trig["has_rejection"] or is_asian_session:
                    setup_type = "WAITING_FOR_REJECTION"
                    direction = "NEUTRAL"
                    setup_reason = f"รอแท่ง M5/15m ปิดยืนยัน Rejection บนแนว Role Reversal Support ({closest_rr.price_mid:.2f})"
                elif risk_usd > MAX_GOLD_SL_USD:
                    setup_type = "REJECTED_SL_TOO_WIDE"
                    direction = "NEUTRAL"
                    setup_reason = f"⚠️ ปฏิเสธ BUY: ระยะ Stop Loss ของ Role Reversal กว้างเกินเกณฑ์ (${risk_usd:.2f} > ${MAX_GOLD_SL_USD:.2f})"
                elif rr_ratio < MIN_GOLD_RR_RATIO:
                    setup_type = "REJECTED_POOR_RR"
                    direction = "NEUTRAL"
                    setup_reason = f"⚠️ ปฏิเสธ BUY: R:R ของ Role Reversal ต่ำเกินไป ({rr_ratio:.2f} < {MIN_GOLD_RR_RATIO:.2f})"
                else:
                    setup_type = "BUY_ROLE_REVERSAL_RETEST"
                    direction = "BUY"
                    setup_reason = f"แนวต้านเดิมถูกทะลุและสลับบทบาทเป็นแนวรับใหม่ (Role Reversal) ยืนยันด้วยแท่งปิด {trigger_tf} ที่ {closest_rr.price_mid:.2f} พร้อม R:R {rr_ratio:.2f}"

            # Broken Support -> New Resistance (SELL Role Reversal)
            elif closest_rr.zone_type == "SUPPORT" and current_price <= closest_rr.price_high:
                trig = _evaluate_rejection_and_danger(bars_5m, bars_15m, closest_rr.price_mid, current_atr, side="SELL")
                down_headroom, support_floor = _calc_sell_headroom(current_price)
                min_req_hr = current_atr * MIN_HEADROOM_ATR_MULT
                m5_rejection_detected = trig["has_5m_rejection"]
                trigger_tf = trig["trigger_tf"]

                target_entry = current_price
                target_sl = closest_rr.price_high + (current_atr * 0.75) + live_spread
                below_demands = [d for d in demands if d["zone_high"] < current_price]
                target_tp = (below_demands[0]["zone_high"] + current_atr * 0.35) if below_demands else (current_price - current_atr * 2.0)
                target_tp = max(target_tp, current_price - 16.0)
                risk_usd = target_sl - target_entry
                reward_usd = target_entry - target_tp
                rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0

                if trig["is_danger"]:
                    setup_type = "REJECTED_ROCKET_SURGE"
                    direction = "NEUTRAL"
                    setup_reason = "⚠️ ปฏิเสธ SELL Role Reversal: แท่งเทียนพุ่งแรง (Rocket Surge) ห้ามขวางจรวด"
                elif down_headroom < min_req_hr:
                    setup_type = "REJECTED_NEAR_SUPPORT_HEADROOM"
                    direction = "NEUTRAL"
                    setup_reason = f"⚠️ ปฏิเสธ SELL Role Reversal: ชิดแนวรับ/Low วัน ({support_floor:.2f}, Headroom {down_headroom:.2f} < 1.5x ATR) ห้ามขายก้นเหว [XAU-RULE-19]"
                elif not trig["has_rejection"] or is_asian_session:
                    setup_type = "WAITING_FOR_REJECTION"
                    direction = "NEUTRAL"
                    setup_reason = f"รอแท่ง M5/15m ปิดยืนยัน Rejection บนแนว Role Reversal Resistance ({closest_rr.price_mid:.2f})"
                elif risk_usd > MAX_GOLD_SL_USD:
                    setup_type = "REJECTED_SL_TOO_WIDE"
                    direction = "NEUTRAL"
                    setup_reason = f"⚠️ ปฏิเสธ SELL: ระยะ Stop Loss ของ Role Reversal กว้างเกินเกณฑ์ (${risk_usd:.2f} > ${MAX_GOLD_SL_USD:.2f})"
                elif rr_ratio < MIN_GOLD_RR_RATIO:
                    setup_type = "REJECTED_POOR_RR"
                    direction = "NEUTRAL"
                    setup_reason = f"⚠️ ปฏิเสธ SELL: R:R ของ Role Reversal ต่ำเกินไป ({rr_ratio:.2f} < {MIN_GOLD_RR_RATIO:.2f})"
                else:
                    setup_type = "SELL_ROLE_REVERSAL_RETEST"
                    direction = "SELL"
                    setup_reason = f"แนวรับเดิมหลุดและสลับบทบาทเป็นแนวต้านใหม่ (Role Reversal) ยืนยันด้วยแท่งปิด {trigger_tf} ที่ {closest_rr.price_mid:.2f} พร้อม R:R {rr_ratio:.2f}"

    active_login = adapter.mt5_client.account_info.get("login") if adapter.mt5_client.account_info else 434552387
    if active_login not in (434552387, 160219615):
        active_login = 434552387
    is_cent_account = (active_login == 160219615)
    account_label = f"Real Cent Exness (#{active_login})" if is_cent_account else f"Demo Exness (#{active_login})"

    live_bar_range = 0.0
    if bars_5m:
        live_bar_range = round(bars_5m[-1].high - bars_5m[-1].low, 2)
    elif bars_15m:
        live_bar_range = round(bars_15m[-1].high - bars_15m[-1].low, 2)

    return {
        "status": setup_type,
        "symbol": "XAUUSD",
        "mt5_symbol": resolved,
        "current_price": round(current_price, 2),
        "spread": round(float(live_spread), 2),
        "current_atr": round(float(current_atr), 2),
        "atr_15m": round(float(current_atr), 2),
        "live_bar_range": live_bar_range,
        "target_account": active_login,
        "account_label": account_label,
        "is_sandbox": not is_cent_account,
        "strategy_name": "Gold S/R, Role Reversal & Demand/Supply (No OB)",
        "trend_indicators": {
            "ema15": ema15_val,
            "ma50": ma50_val,
            "h1_ema50": h1_ema50_val,
            "trend": m15_trend,
            "h1_trend": h1_trend,
            "m15_structure": m15_structure,
            "h1_structure": h1_structure,
        },
        "session_info": session_info,
        "demand_zones": demands,
        "supply_zones": supplies,
        "nearest_demand": nearest_demand,
        "nearest_supply": nearest_supply,
        "fibo_golden_zone": best_fibo,
        "fibo_buy": best_fibo_buy,
        "fibo_sell": best_fibo_sell,
        "major_fibo": major_fibo,
        "minor_fibo": minor_fibo,
        "fibo_history": fibo_history,
        "double_confluence_active": double_confluence_active,
        "role_reversal_count": len(role_reversals),
        "execution_mode": order_execution_mode,
        "trigger_timeframe": trigger_tf,
        "m5_rejection_detected": m5_rejection_detected,
        "recommended_direction": direction,
        "recommended_entry": round(target_entry, 2),
        "recommended_sl": round(target_sl, 2),
        "recommended_tp": round(target_tp, 2),
        "rr_ratio": round(rr_ratio, 2),
        "risk_usd": round(risk_usd, 2),
        "reward_usd": round(reward_usd, 2),
        "pullback_entry_recommended": pullback_entry_recommended,
        "setup_reason": setup_reason,
        "order_block_excluded": True,
        "antigravity_command": f"python -m src.execution.agent_bridge execute --symbol {resolved} --direction {direction} --volume {0.06 if is_cent_account else 0.01} --sl {target_sl:.2f} --tp {target_tp:.2f}" if direction != "NEUTRAL" else "N/A (รอจังหวะเข้าโซน)"
    }
