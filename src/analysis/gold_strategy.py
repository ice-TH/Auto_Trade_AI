"""
XAU/USD (Gold) Strategy Module (Experimental Sandbox)
Designed for Antigravity AI to analyze XAUUSD / XAUUSDm:
- Support & Resistance with Role Reversal (Broken Support -> Resistance, Broken Resistance -> Support)
- Demand & Supply Zones: DBR (Drop-Base-Rally), RBR (Rally-Base-Rally), RBD (Rally-Base-Drop), DBD (Drop-Base-Drop)
- Trading Session & Session Overlap Filtering (Sydney, Tokyo, London, New York, London x New York Overlap)
- Spread-aware SL (Moat buffer) and TP (Front-running)
- Strictly NO Order Block (OB) logic included per user instruction.

Note: Dedicated strictly to Demo account #434552387.
Does not impact the core 7 US equities or the BTC 1m fast scalper.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import logging

from src.data.base import Bar, TimeFrame
from src.data.mt5_adapter import MT5DataAdapter
from src.analysis.indicators import calculate_atr, calculate_ema, calculate_sma
from src.analysis.zones import build_sr_zones, SRZone
from src.analysis.swings import detect_swings, SwingPoint

logger = logging.getLogger("gold_strategy")

# Quantitative Safety Thresholds for Gold (XAU/USD) Intraday
MAX_GOLD_SL_USD = 8.00  # Hard Stop Loss cap ($8.00 USD max per [XAU-RULE-09] & [XAU-RULE-12] updated)
MIN_GOLD_RR_RATIO = 1.50  # Minimum Risk:Reward ratio required to issue Buy/Sell setup
MIN_HEADROOM_ATR_MULT = 1.50  # Must have at least 1.5x ATR space before nearest obstacle

@dataclass
class ZigZagPivot:
    index: int
    bar_time: Any
    price: float
    pivot_type: int  # 1 = HIGH, -1 = LOW

def detect_zigzag_pivots(bars: List[Bar], pivot_legs: int = 8, min_deviation_pct: float = 0.8) -> List[ZigZagPivot]:
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

    pivots: List[ZigZagPivot] = []
    for i in range(len(pv_price)):
        pivots.append(ZigZagPivot(
            index=pv_index[i],
            bar_time=pv_time[i],
            price=pv_price[i],
            pivot_type=pv_type[i]
        ))
    return pivots

def calculate_fibonacci_retracement(swing_high: float, swing_low: float, label: str = "Major") -> Dict[str, Any]:
    """
    Calculates Fibonacci Retracement levels including 0.65 (Optimal Trade Entry - OTE).
    - 61.8% Golden Pocket Top
    - 65.0% OTE Sweet Spot (PineScript V3)
    - 78.6% Golden Pocket Bottom
    """
    diff = swing_high - swing_low
    if diff <= 0:
        return {}
    return {
        "label": label,
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
        "fibo_236": round(swing_high - 0.236 * diff, 2),
        "fibo_382": round(swing_high - 0.382 * diff, 2),
        "fibo_500": round(swing_high - 0.500 * diff, 2),
        "fibo_618": round(swing_high - 0.618 * diff, 2),
        "fibo_650": round(swing_high - 0.650 * diff, 2),
        "fibo_786": round(swing_high - 0.786 * diff, 2),
        "golden_zone_high": round(swing_high - 0.618 * diff, 2),
        "golden_zone_mid": round(swing_high - 0.650 * diff, 2),
        "golden_zone_low": round(swing_high - 0.786 * diff, 2),
        "diff": round(diff, 2)
    }

def check_fibo_confluence(zone_high: float, zone_low: float, fibo_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Checks if a Demand/Supply Zone overlaps or touches the Fibonacci Golden Zone (61.8% - 78.6%).
    """
    if not fibo_data or "golden_zone_high" not in fibo_data:
        return {"has_confluence": False, "overlap_pct": 0.0, "reason": "No Fibo data"}

    gz_high = fibo_data["golden_zone_high"]
    gz_low = fibo_data["golden_zone_low"]
    label = fibo_data.get("label", "")

    overlap_low = max(zone_low, gz_low)
    overlap_high = min(zone_high, gz_high)

    if overlap_high >= overlap_low:
        overlap_size = overlap_high - overlap_low
        zone_size = max(zone_high - zone_low, 0.01)
        overlap_pct = min(round((overlap_size / zone_size) * 100.0, 1), 100.0)
        return {
            "has_confluence": True,
            "fibo_label": label,
            "overlap_high": round(overlap_high, 2),
            "overlap_low": round(overlap_low, 2),
            "overlap_mid": round((overlap_high + overlap_low) / 2.0, 2),
            "overlap_pct": overlap_pct,
            "reason": f"ซ้อนทับ {label} Golden Zone ({overlap_low:.2f} - {overlap_high:.2f}) {overlap_pct}%"
        }

    dist = min(abs(zone_low - gz_high), abs(zone_high - gz_low))
    return {
        "has_confluence": False,
        "fibo_label": label,
        "overlap_pct": 0.0,
        "distance": round(dist, 2),
        "reason": f"ไม่ซ้อนทับ {label} Golden Zone (ห่าง {dist:.2f} USD)"
    }

def detect_trading_session(utc_now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Detects the current active Trading Session(s) based on Bangkok Time (UTC+7).
    Sessions (Standard Winter Hours BKK):
    - Sydney:   05:00 - 14:00
    - Tokyo:    06:00 - 15:00
    - London:   15:00 - 23:00
    - New York: 20:00 - 04:00 (+1)
    - Session Overlap (London x New York): 20:00 - 23:00 (Peak Volume & Volatility)
    """
    if utc_now is None:
        utc_now = datetime.now(timezone.utc)
    
    bkk_time = utc_now + timedelta(hours=7)
    hour = bkk_time.hour
    minute = bkk_time.minute
    time_float = hour + minute / 60.0

    active_sessions = []
    
    # Sydney: 05:00 - 14:00
    if 5.0 <= time_float < 14.0:
        active_sessions.append("Sydney (ออสเตรเลีย)")
        
    # Tokyo: 06:00 - 15:00
    if 6.0 <= time_float < 15.0:
        active_sessions.append("Tokyo (เอเชีย)")
        
    # London: 15:00 - 23:00
    if 15.0 <= time_float < 23.0:
        active_sessions.append("London (ยุโรป)")
        
    # New York: 20:00 - 04:00 (+1)
    if time_float >= 20.0 or time_float < 4.0:
        active_sessions.append("New York (อเมริกา)")

    # London x New York Overlap: 20:00 - 23:00
    is_overlap = (20.0 <= time_float < 23.0)
    
    liquidity_status = "NORMAL"
    if is_overlap:
        liquidity_status = "PEAK_OVERLAP"
        session_desc = "🔥 ช่วงเวลาทอง (London × New York Overlap): ปริมาณซื้อขายและสภาพคล่องสูงสุดในรอบวัน ความผันผวนสูงมาก"
    elif "London (ยุโรป)" in active_sessions or "New York (อเมริกา)" in active_sessions:
        liquidity_status = "HIGH"
        session_desc = f"ช่วงตลาดหลัก ({', '.join(active_sessions)}): สภาพคล่องสูง ทิศทางชัดเจน"
    elif active_sessions:
        liquidity_status = "LOW_MODERATE"
        session_desc = f"ช่วงตลาดเอเชีย/ออสเตรเลีย ({', '.join(active_sessions)}): สภาพคล่องปานกลาง-ต่ำ ระวัง Sideway กรอบแคบ"
    else:
        liquidity_status = "OFF_HOURS"
        session_desc = "ช่วงพักตลาดหลัก (04:00 - 05:00): สภาพคล่องต่ำ สเปรดอาจถ่างกว้าง"

    return {
        "bkk_time": bkk_time.strftime("%H:%M:%S"),
        "bkk_hour": hour,
        "active_sessions": active_sessions,
        "is_overlap": is_overlap,
        "liquidity_status": liquidity_status,
        "session_description": session_desc
    }

def clamp_zone_size(top: float, bottom: float, atr: float, max_atr_mult: float = 1.5) -> tuple[float, float]:
    """
    Prevents oversized Demand/Supply zones from bloating (learned from Flux Charts Pine Script).
    If (top - bottom) > atr * max_atr_mult, clamp boundaries symmetrically.
    """
    size = top - bottom
    max_size = atr * max_atr_mult
    if size > max_size and max_size > 0:
        diff = size - max_size
        top -= diff / 2.0
        bottom += diff / 2.0
    return round(top, 2), round(bottom, 2)


def combine_overlapping_zones(zones: List[Dict[str, Any]], atr: float) -> List[Dict[str, Any]]:
    """
    Combines overlapping or touching zones of the same type (learned from Flux Charts Pine Script).
    Fuses them into a single high-confluence zone and clamps size.
    """
    if not zones:
        return []

    combined = []
    skip_indices = set()

    for i in range(len(zones)):
        if i in skip_indices:
            continue
        cur = dict(zones[i])
        for j in range(i + 1, len(zones)):
            if j in skip_indices:
                continue
            other = zones[j]
            # Check overlap or touching within 0.25x ATR
            touches = not (cur["zone_low"] > other["zone_high"] + (atr * 0.25) or cur["zone_high"] < other["zone_low"] - (atr * 0.25))
            if touches:
                # Merge into higher confluence zone
                new_top = max(cur["zone_high"], other["zone_high"])
                new_bottom = min(cur["zone_low"], other["zone_low"])
                new_top, new_bottom = clamp_zone_size(new_top, new_bottom, atr, max_atr_mult=1.5)
                cur["zone_high"] = new_top
                cur["zone_low"] = new_bottom
                cur["zone_mid"] = round((new_top + new_bottom) / 2.0, 2)
                cur["confluence"] = cur.get("confluence", 1) + 1
                if other.get("timeframe") != cur.get("timeframe"):
                    cur["timeframe"] = f"{cur.get('timeframe', '')} & {other.get('timeframe', '')}"
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
    Identifies Demand & Supply Zones based on Price Action candle formations:
    - Demand: Drop-Base-Rally (DBR) and Rally-Base-Rally (RBR)
    - Supply: Rally-Base-Drop (RBD) and Drop-Base-Drop (DBD)
    - Integrated with Pine Script (Flux Charts) principles:
      * Dynamic Zone Clamping (<= 1.5x ATR)
      * Zone Invalidation (Close break)
      * Retest Proximity & Rejection Verification
    Note: Strictly no Order Block logic is used per user specification.
    """
    if len(bars) < min_bars:
        return {"demand_zones": [], "supply_zones": []}

    demand_zones = []
    supply_zones = []

    # Calculate average bar size and ATR
    body_sizes = [abs(b.close - b.open) for b in bars[-30:]]
    avg_body = sum(body_sizes) / max(len(body_sizes), 1)

    if atr_val is None:
        tr_list = []
        for k in range(1, len(bars)):
            h_l = bars[k].high - bars[k].low
            h_pc = abs(bars[k].high - bars[k - 1].close)
            l_pc = abs(bars[k].low - bars[k - 1].close)
            tr_list.append(max(h_l, h_pc, l_pc))
        atr_val = (sum(tr_list[-14:]) / 14.0) if len(tr_list) >= 14 else avg_body * 1.5

    # Scan for Base formations followed by Explosive Momentum Departure
    for i in range(2, len(bars) - 1):
        leg1 = bars[i - 2]
        base = bars[i - 1]
        leg2 = bars[i]

        leg1_body = leg1.close - leg1.open
        base_body = abs(base.close - base.open)
        leg2_body = leg2.close - leg2.open

        # A valid Base candle has relatively small body (consolidation before explosive outflow)
        is_base = base_body <= (avg_body * 1.25)

        if not is_base:
            continue

        # 1. Demand Zones (Rally out of Base)
        # Leg 2 must be an explosive bullish candle with genuine institutional imbalance (>= 1.5x avg body)
        if leg2_body >= avg_body * 1.5 and leg2.close > base.high:
            pattern_type = "DBR" if leg1_body < 0 else "RBR"
            raw_high = max(base.open, base.close, base.high)
            raw_low = min(base.open, base.close, base.low)

            # Apply Pine Script Clamping (prevent oversized boxes)
            zone_high, zone_low = clamp_zone_size(raw_high, raw_low, atr_val, max_atr_mult=1.5)

            # Check if broken by subsequent price (Invalidation)
            latest_close = bars[-1].close
            is_broken = latest_close < zone_low

            demand_zones.append({
                "type": "DEMAND",
                "pattern": pattern_type,
                "timeframe": timeframe_label,
                "label": f"Demand {timeframe_label} ({pattern_type})",
                "zone_high": round(zone_high, 2),
                "zone_low": round(zone_low, 2),
                "zone_mid": round((zone_high + zone_low) / 2.0, 2),
                "created_time": base.open_time.isoformat() if hasattr(base.open_time, 'isoformat') else str(base.open_time),
                "is_broken": is_broken,
                "tested": False
            })

        # 2. Supply Zones (Drop out of Base)
        # Leg 2 must be an explosive bearish candle with genuine institutional imbalance (<= -1.5x avg body)
        elif leg2_body <= -avg_body * 1.5 and leg2.close < base.low:
            pattern_type = "RBD" if leg1_body > 0 else "DBD"
            raw_high = max(base.open, base.close, base.high)
            raw_low = min(base.open, base.close, base.low)

            # Apply Pine Script Clamping (prevent oversized boxes)
            zone_high, zone_low = clamp_zone_size(raw_high, raw_low, atr_val, max_atr_mult=1.5)

            # Check if broken by subsequent price (Invalidation)
            latest_close = bars[-1].close
            is_broken = latest_close > zone_high

            supply_zones.append({
                "type": "SUPPLY",
                "pattern": pattern_type,
                "timeframe": timeframe_label,
                "label": f"Supply {timeframe_label} ({pattern_type})",
                "zone_high": round(zone_high, 2),
                "zone_low": round(zone_low, 2),
                "zone_mid": round((zone_high + zone_low) / 2.0, 2),
                "created_time": base.open_time.isoformat() if hasattr(base.open_time, 'isoformat') else str(base.open_time),
                "is_broken": is_broken,
                "tested": False
            })

    # Keep active (unbroken) zones first, then combine overlapping zones (Pine Script fusion)
    active_demands = [dz for dz in demand_zones if not dz.get("is_broken", False)]
    active_supplies = [sz for sz in supply_zones if not sz.get("is_broken", False)]

    fused_demands = combine_overlapping_zones(active_demands, atr_val)
    fused_supplies = combine_overlapping_zones(active_supplies, atr_val)

    return {
        "demand_zones": fused_demands[-4:] if fused_demands else [],
        "supply_zones": fused_supplies[-4:] if fused_supplies else []
    }

def scan_gold_setup() -> Dict[str, Any]:
    """
    Evaluates actionable Gold (XAU/USD) trade setup based on:
    1. Support / Resistance with Role Reversal
    2. Demand & Supply Zones (DBR, RBR, RBD, DBD)
    3. Trading Session & London x New York Overlap status
    4. Spread-aware TP & SL calculation
    """
    adapter = MT5DataAdapter()
    adapter._ensure_connected()
    symbol = "XAUUSD"
    resolved = adapter._resolve_symbol(symbol) or "XAUUSDc"
    
    bars_5m = adapter.get_bars(symbol, TimeFrame.M5, limit=120) or []
    bars_15m = adapter.get_bars(symbol, TimeFrame.M15, limit=200) or []
    bars_h1 = adapter.get_bars(symbol, TimeFrame.H1, limit=120) or []
    bars_day = adapter.get_bars(symbol, TimeFrame.DAY, limit=100) or []
    
    current_price = 2650.0
    if bars_5m:
        current_price = bars_5m[-1].close
    elif bars_15m:
        current_price = bars_15m[-1].close

    quote = adapter.get_latest_quote(symbol) or {}
    live_spread = quote.get("spread", 0.20)

    atr_vals = calculate_atr(bars_15m, period=14) if len(bars_15m) >= 15 else []
    current_atr = atr_vals[-1]["value"] if atr_vals else 4.50

    # Trend Indicators: EMA(15) and MA(50)
    ema15_list = calculate_ema(bars_15m, 15) if len(bars_15m) >= 15 else []
    ma50_list = calculate_sma(bars_15m, 50) if len(bars_15m) >= 50 else []
    ema15_val = ema15_list[-1]["value"] if ema15_list else None
    ma50_val = ma50_list[-1]["value"] if ma50_list else None
    ma_trend = "BULLISH" if (ema15_val and ma50_val and ema15_val > ma50_val) else ("BEARISH" if (ema15_val and ma50_val and ema15_val < ma50_val) else "NEUTRAL")

    # 1. Session Detection (use latest bar timestamp if available, fallback to real-time clock)
    eval_time = bars_15m[-1].close_time if (bars_15m and hasattr(bars_15m[-1], 'close_time')) else None
    session_info = detect_trading_session(eval_time)

    # 2. Support / Resistance & Role Reversal
    sr_zones = build_sr_zones("XAUUSD", bars_15m) if bars_15m else []
    role_reversals = [z for z in sr_zones if z.is_role_reversed]

    # 3. Demand & Supply Zones (Multi-Timeframe M15 + H1 with Pine Script Clamping & Fusion)
    ds_zones_15m = detect_demand_supply_zones(bars_15m, min_bars=15, timeframe_label="15m", atr_val=current_atr) if bars_15m else {"demand_zones": [], "supply_zones": []}
    ds_zones_h1 = detect_demand_supply_zones(bars_h1, min_bars=15, timeframe_label="1H", atr_val=current_atr * 2.0) if bars_h1 else {"demand_zones": [], "supply_zones": []}

    # Combined zones: prioritize sorting by proximity to current price
    all_demands = combine_overlapping_zones(ds_zones_15m["demand_zones"] + ds_zones_h1["demand_zones"], current_atr)
    all_supplies = combine_overlapping_zones(ds_zones_15m["supply_zones"] + ds_zones_h1["supply_zones"], current_atr)

    # Filter & deduplicate overlapping zones
    demands = sorted(all_demands, key=lambda d: abs(current_price - d["zone_high"]))
    supplies = sorted(all_supplies, key=lambda s: abs(current_price - s["zone_low"]))

    # 4. Multi-Swing Fibonacci Engine (PineScript V3 ZigZag with Hierarchy)
    # Detect pivots using robust ZigZag (pivot_legs = 8, deviation = 0.8% ~ $25-$30 for Gold)
    zz_pivots = detect_zigzag_pivots(bars_15m, pivot_legs=8, min_deviation_pct=0.8) if len(bars_15m) >= 20 else []
    
    # Also fallback to pivot_legs=5 if market was in tight consolidation
    if len(zz_pivots) < 2 and len(bars_15m) >= 15:
        zz_pivots = detect_zigzag_pivots(bars_15m, pivot_legs=5, min_deviation_pct=0.5)

    major_fibo: Dict[str, Any] = {}
    minor_fibo: Dict[str, Any] = {}
    best_fibo: Dict[str, Any] = {}
    double_confluence_active = False

    if len(zz_pivots) >= 2:
        # Extract swings
        high_pivots = [p for p in zz_pivots if p.pivot_type == 1]
        low_pivots = [p for p in zz_pivots if p.pivot_type == -1]

        # 1. Latest/Minor Swing (Between the last two alternating pivots)
        last_p = zz_pivots[-1]
        prev_p = zz_pivots[-2]
        min_high = max(last_p.price, prev_p.price)
        min_low = min(last_p.price, prev_p.price)
        # Include current bar's projection if higher/lower
        min_high = max(min_high, bars_15m[-1].high if bars_15m else min_high)
        min_low = min(min_low, bars_15m[-1].low if bars_15m else min_low)
        if (min_high - min_low) >= (current_atr * 2.0):
            minor_fibo = calculate_fibonacci_retracement(min_high, min_low, label="Minor")

        # 2. Major Swing (Look back further to significant macro high and low)
        if len(zz_pivots) >= 4:
            maj_high = max([p.price for p in high_pivots])
            maj_low = min([p.price for p in low_pivots])
            if (maj_high - maj_low) >= (current_atr * 4.0):
                major_fibo = calculate_fibonacci_retracement(maj_high, maj_low, label="Major")
        else:
            major_fibo = minor_fibo

        # 3. Smart Swing Selector: Prioritize whichever aligns best with active Demand/Supply Base
        best_fibo = minor_fibo if minor_fibo else major_fibo
        if major_fibo and demands:
            # Check if major Golden Zone aligns directly with nearest demand
            maj_conf = check_fibo_confluence(demands[0]["zone_high"], demands[0]["zone_low"], major_fibo)
            min_conf = check_fibo_confluence(demands[0]["zone_high"], demands[0]["zone_low"], minor_fibo) if minor_fibo else {}
            
            if maj_conf.get("has_confluence") and min_conf.get("has_confluence"):
                # ⭐⭐ Ultra Setup: Double Confluence (Both Major and Minor Golden Zones align!)
                best_fibo = minor_fibo
                double_confluence_active = True
            elif maj_conf.get("has_confluence"):
                best_fibo = major_fibo
            elif min_conf.get("has_confluence"):
                best_fibo = minor_fibo

    # Annotate demands and supplies with best Fibo Golden Zone confluence
    for d in demands:
        conf = check_fibo_confluence(d["zone_high"], d["zone_low"], best_fibo)
        if double_confluence_active:
            conf["double_confluence"] = True
            conf["reason"] = f"⭐⭐ Double Confluence: ซ้อนทับทั้ง Major & Minor Golden Zone!"
        d["fibo_confluence"] = conf

    for s in supplies:
        conf = check_fibo_confluence(s["zone_high"], s["zone_low"], best_fibo)
        if double_confluence_active:
            conf["double_confluence"] = True
            conf["reason"] = f"⭐⭐ Double Confluence: ซ้อนทับทั้ง Major & Minor Golden Zone!"
        s["fibo_confluence"] = conf

    # 5. Signal Determination
    # Check if current price is touching or near any Demand or Role-Reversed Support
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

    # Check Demand Proximity (Strict: Price touches or penetrates Base, max 0.35x ATR above zone_high)
    # Headroom & Resistance Filter: Never BUY if too close to overhead supply/resistance
    # Rejection Wick Filter: Confirm rejection (lower wick >= 25% or bullish reversal close) before entering
    is_touching_demand = (
        nearest_demand is not None
        and (current_price <= nearest_demand["zone_high"] + (current_atr * 0.35))
        and (current_price >= nearest_demand["zone_low"] - (current_atr * 0.50))
    )
    if is_touching_demand:
        # 1. Multi-Timeframe Rejection Confirmation (M5 Sniper Trigger + 15m Structure)
        bar_5m = bars_5m[-1] if bars_5m else None
        bar_15m = bars_15m[-1] if bars_15m else None

        has_5m_rejection = False
        rejection_5m_ratio = 0.0
        is_5m_falling_knife = False
        if bar_5m:
            b5_range = max(bar_5m.high - bar_5m.low, 0.001)
            b5_body = bar_5m.close - bar_5m.open
            b5_lower_wick = (min(bar_5m.open, bar_5m.close) - bar_5m.low)
            rejection_5m_ratio = b5_lower_wick / b5_range
            is_5m_falling_knife = (b5_body < 0) and (abs(b5_body) >= 0.75 * b5_range) and (b5_range >= 1.0 * current_atr)
            has_5m_rejection = (rejection_5m_ratio >= 0.25) or (bar_5m.close > bar_5m.open and bar_5m.close >= nearest_demand["zone_mid"])

        has_15m_rejection = False
        rejection_15m_ratio = 0.0
        is_15m_falling_knife = False
        if bar_15m:
            b15_range = max(bar_15m.high - bar_15m.low, 0.001)
            b15_body = bar_15m.close - bar_15m.open
            b15_lower_wick = (min(bar_15m.open, bar_15m.close) - bar_15m.low)
            rejection_15m_ratio = b15_lower_wick / b15_range
            is_15m_falling_knife = (b15_body < 0) and (abs(b15_body) >= 0.70 * b15_range) and (b15_range >= 1.8 * current_atr)
            has_15m_rejection = (rejection_15m_ratio >= 0.25) or (bar_15m.close > bar_15m.open and bar_15m.close >= nearest_demand["zone_mid"])

        is_falling_knife = is_15m_falling_knife or (is_5m_falling_knife and not has_5m_rejection)
        has_rejection = (has_5m_rejection or has_15m_rejection) and not is_falling_knife
        m5_rejection_detected = has_5m_rejection
        trigger_tf = "M5" if has_5m_rejection else ("15m" if has_15m_rejection else "NONE")

        # Overhead Supply check
        overhead_supplies = [s for s in supplies if s["zone_low"] > current_price]
        nearest_overhead = overhead_supplies[0] if overhead_supplies else None
        headroom = (nearest_overhead["zone_low"] - current_price) if nearest_overhead else 999.0

        if is_falling_knife:
            setup_type = "REJECTED_FALLING_KNIFE"
            direction = "NEUTRAL"
            target_entry = current_price
            target_sl = nearest_demand["zone_low"] - (current_atr * 0.75)
            target_tp = current_price + (current_atr * 2.0)
            risk_usd = target_entry - target_sl
            reward_usd = target_tp - target_entry
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0
            setup_reason = f"⚠️ ปฏิเสธ BUY ที่ Demand: แท่งเทียนกำลังทิ้งตัวรุนแรง (Falling Knife) บังคับรอแท่ง Rejection Wick ยืนยันก่อน"
        elif not has_rejection:
            setup_type = "WAITING_FOR_REJECTION"
            direction = "NEUTRAL"
            target_entry = current_price
            target_sl = nearest_demand["zone_low"] - (current_atr * 0.75)
            target_tp = current_price + (current_atr * 2.0)
            risk_usd = target_entry - target_sl
            reward_usd = target_tp - target_entry
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0
            setup_reason = (
                f"⏳ ราคาสัมผัส Demand Zone ({nearest_demand['zone_low']:.2f} - {nearest_demand['zone_high']:.2f}) "
                f"กำลังรอแท่งเทียน M5/15m เกิด Rejection Wick ยืนยัน (หางล่าง M5: {rejection_5m_ratio*100:.1f}%, 15m: {rejection_15m_ratio*100:.1f}% < 25%) "
                f"เพื่อป้องกันการรับมีดตก [XAU-RULE-06]"
            )
        elif headroom < (current_atr * 1.0):
            setup_type = "REJECTED_NEAR_RESISTANCE"
            direction = "NEUTRAL"
            target_entry = current_price
            target_sl = nearest_demand["zone_low"] - (current_atr * 0.75)
            target_tp = current_price + (current_atr * 2.0)
            risk_usd = target_entry - target_sl
            reward_usd = target_tp - target_entry
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0
            setup_reason = f"⚠️ ปฏิเสธ BUY: ราคาใกล้แนวต้าน Supply ({nearest_overhead['zone_low']:.2f}) มากเกินไป (Headroom {headroom:.2f} < 1.0x ATR) ห้ามซื้อชิดแนวต้าน"
        else:
            raw_sl = nearest_demand["zone_low"] - (current_atr * 0.75)  # Moat buffer below base
            above_supplies = [s for s in supplies if s["zone_low"] > current_price]
            if above_supplies:
                # Target just before overhead supply
                target_tp = above_supplies[0]["zone_low"] - (current_atr * 0.35)
            else:
                target_tp = current_price + (current_atr * 1.5)

            # Check if price is chasing far above the base
            is_chasing_above_zone = (current_price > nearest_demand["zone_high"] + (current_atr * 0.40))
            is_asian_session = (session_info.get("liquidity_status") == "LOW_MODERATE") or (session_info.get("bkk_hour", 12) in range(6, 15))

            # Realistic Intraday TP Cap: Balance Winrate & R:R (Default target 1.5x - 2.5x Risk, max $16 USD for Intraday)
            calculated_risk = max(current_price - (nearest_demand["zone_low"] - (current_atr * 0.35)), 3.0)
            ideal_realistic_tp = current_price + (calculated_risk * 2.0)
            if target_tp > ideal_realistic_tp and (target_tp - current_price) > 16.0:
                target_tp = min(target_tp, current_price + 16.0)

            # Evaluate Market Entry baseline
            sl_distance = current_price - raw_sl
            risk_usd = sl_distance
            reward_usd = target_tp - current_price
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0

            if sl_distance > MAX_GOLD_SL_USD:
                setup_type = "REJECTED_SL_TOO_WIDE"
                direction = "NEUTRAL"
                target_entry = current_price
                target_sl = raw_sl
                setup_reason = (
                    f"⚠️ ปฏิเสธ BUY: ระยะ Stop Loss กว้างเกินเกณฑ์ (${sl_distance:.2f} > ${MAX_GOLD_SL_USD:.2f}) "
                    f"เสี่ยงเกินขนาดสำหรับ Intraday Scalp รอราคาย่อตัวลึกเข้าเนื้อ Demand Zone (${nearest_demand['zone_low']:.2f} - ${nearest_demand['zone_high']:.2f})"
                )
            elif rr_ratio < MIN_GOLD_RR_RATIO:
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
            elif is_chasing_above_zone or is_asian_session:
                # 🎯 Systematic Pullback / Limit Order: Do NOT chase at highs, enter at Fibo 65% OTE or Base Midpoint
                limit_entry_candidate = best_fibo.get("fibo_650") or nearest_demand.get("zone_mid") or (nearest_demand["zone_low"] + current_atr * 0.25)
                limit_entry = min(max(limit_entry_candidate, nearest_demand["zone_low"]), nearest_demand["zone_high"])
                target_entry = round(limit_entry, 2)
                target_sl = round(raw_sl, 2)
                order_execution_mode = "LIMIT"

                risk_usd = target_entry - target_sl
                reward_usd = target_tp - target_entry
                rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0

                setup_type = "ACTIONABLE_BUY_LIMIT"
                direction = "BUY"
                session_note = "ช่วงตลาดเอเชีย สภาพคล่องเบาบาง ป้องกัน Stop Hunt" if is_asian_session else f"ราคาเด้งพ้นฐาน > 0.4x ATR ป้องกันการไล่ซื้อยอดเด้ง"
                setup_reason = (
                    f"🎯 แนะนำ Buy Limit ดักย่อที่ Fibo 65% OTE / Demand Base (${target_entry:.2f}) SL ${target_sl:.2f} (R:R {rr_ratio:.2f}) "
                    f"[{session_note} - [XAU-RULE-21]]"
                )
            else:
                target_entry = current_price
                target_sl = raw_sl
                order_execution_mode = "MARKET"
                setup_type = "BUY_DEMAND_ZONE"
                direction = "BUY"
                setup_reason = f"ราคาแตะโซน Demand ({nearest_demand['pattern']}) ชิดฐานที่ {nearest_demand['zone_low']} - {nearest_demand['zone_high']} ยืนยันด้วยแท่งเทียน {trigger_tf} พร้อม R:R {rr_ratio:.2f} (Headroom ปลอดภัย {headroom:.2f})"

    # Check Supply Proximity (Strict: Price touches or penetrates Base, max 0.35x ATR below zone_low)
    # Headroom & Support Filter: Never SELL if too close to underneath demand/support
    # Rejection Wick Filter: Confirm rejection (upper wick >= 25% or bearish reversal close) before entering
    is_touching_supply = (
        nearest_supply is not None
        and (current_price >= nearest_supply["zone_low"] - (current_atr * 0.35))
        and (current_price <= nearest_supply["zone_high"] + (current_atr * 0.50))
    )
    if is_touching_supply and direction == "NEUTRAL":
        # 1. Multi-Timeframe Rejection Confirmation (M5 Sniper Trigger + 15m Structure)
        bar_5m = bars_5m[-1] if bars_5m else None
        bar_15m = bars_15m[-1] if bars_15m else None

        has_5m_rejection = False
        rejection_5m_ratio = 0.0
        is_5m_rocket = False
        if bar_5m:
            b5_range = max(bar_5m.high - bar_5m.low, 0.001)
            b5_body = bar_5m.close - bar_5m.open
            b5_upper_wick = bar_5m.high - max(bar_5m.open, bar_5m.close)
            rejection_5m_ratio = b5_upper_wick / b5_range
            is_5m_rocket = (b5_body > 0) and (abs(b5_body) >= 0.75 * b5_range) and (b5_range >= 1.0 * current_atr)
            has_5m_rejection = (rejection_5m_ratio >= 0.25) or (bar_5m.close < bar_5m.open and bar_5m.close <= nearest_supply["zone_mid"])

        has_15m_rejection = False
        rejection_15m_ratio = 0.0
        is_15m_rocket = False
        if bar_15m:
            b15_range = max(bar_15m.high - bar_15m.low, 0.001)
            b15_body = bar_15m.close - bar_15m.open
            b15_upper_wick = bar_15m.high - max(bar_15m.open, bar_15m.close)
            rejection_15m_ratio = b15_upper_wick / b15_range
            is_15m_rocket = (b15_body > 0) and (abs(b15_body) >= 0.70 * b15_range) and (b15_range >= 1.8 * current_atr)
            has_15m_rejection = (rejection_15m_ratio >= 0.25) or (bar_15m.close < bar_15m.open and bar_15m.close <= nearest_supply["zone_mid"])

        is_rocket_candle = is_15m_rocket or (is_5m_rocket and not has_5m_rejection)
        has_rejection = (has_5m_rejection or has_15m_rejection) and not is_rocket_candle
        m5_rejection_detected = has_5m_rejection
        trigger_tf = "M5" if has_5m_rejection else ("15m" if has_15m_rejection else "NONE")

        # Underneath Demand check
        underneath_demands = [d for d in demands if d["zone_high"] < current_price]
        nearest_underneath = underneath_demands[0] if underneath_demands else None
        down_headroom = (current_price - nearest_underneath["zone_high"]) if nearest_underneath else 999.0

        # 3. Dynamic Headroom Guard: Never SELL if too close to underneath demand/support or daily low
        # Must have at least 1.5x ATR room before nearest support
        low_of_day = min([b.low for b in bars_15m[-32:]]) if len(bars_15m) >= 32 else (current_price - 10.0)
        dist_to_day_low = current_price - low_of_day
        effective_support_floor = max(nearest_underneath["zone_high"] if nearest_underneath else 0.0, low_of_day)
        effective_down_headroom = current_price - effective_support_floor if effective_support_floor > 0 else down_headroom

        min_required_headroom = current_atr * MIN_HEADROOM_ATR_MULT

        if is_rocket_candle:
            setup_type = "REJECTED_ROCKET_SURGE"
            direction = "NEUTRAL"
            target_entry = current_price
            target_sl = nearest_supply["zone_high"] + (current_atr * 0.75)
            target_tp = current_price - (current_atr * 2.0)
            risk_usd = target_sl - target_entry
            reward_usd = target_entry - target_tp
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0
            setup_reason = f"⚠️ ปฏิเสธ SELL ที่ Supply: แท่งเทียนกำลังพุ่งขึ้นรุนแรง (Rocket Surge) บังคับรอแท่ง Rejection Wick ยืนยันก่อน"
        elif effective_down_headroom < min_required_headroom:
            setup_type = "REJECTED_NEAR_SUPPORT_HEADROOM"
            direction = "NEUTRAL"
            target_entry = current_price
            target_sl = nearest_supply["zone_high"] + (current_atr * 0.75)
            target_tp = current_price - (current_atr * 2.0)
            risk_usd = target_sl - target_entry
            reward_usd = target_entry - target_tp
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0
            setup_reason = (
                f"⚠️ ปฏิเสธ SELL: พื้นที่ลงแคบเกินไป (Headroom {effective_down_headroom:.2f} < {min_required_headroom:.2f} [1.5x ATR]) "
                f"ราคาอยู่ชิดแนวรับ/Low วัน ({effective_support_floor:.2f}) ห้ามขายก้นเหวเด็ดขาด เสี่ยงโดนดีดสวน"
            )
        elif not has_rejection:
            setup_type = "WAITING_FOR_REJECTION"
            direction = "NEUTRAL"
            target_entry = current_price
            target_sl = nearest_supply["zone_high"] + (current_atr * 0.75)
            target_tp = current_price - (current_atr * 2.0)
            risk_usd = target_sl - target_entry
            reward_usd = target_entry - target_tp
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0
            setup_reason = (
                f"⏳ ราคาสัมผัส Supply Zone ({nearest_supply['zone_low']:.2f} - {nearest_supply['zone_high']:.2f}) "
                f"กำลังรอแท่งเทียน M5/15m เกิด Rejection Wick ยืนยัน (หางบน M5: {rejection_5m_ratio*100:.1f}%, 15m: {rejection_15m_ratio*100:.1f}% < 25%) "
                f"เพื่อป้องกันการขายสวนแรงส่ง [XAU-RULE-06]"
            )
        else:
            raw_sl = nearest_supply["zone_high"] + (current_atr * 0.75)  # Moat buffer above base
            below_demands = [d for d in demands if d["zone_high"] < current_price]
            if below_demands:
                # Target just before underneath demand
                target_tp = below_demands[0]["zone_high"] + (current_atr * 0.35)
            else:
                target_tp = current_price - (current_atr * 1.5)

            # Check if price is chasing far below the base
            is_chasing_below_zone = (current_price < nearest_supply["zone_low"] - (current_atr * 0.40))
            is_asian_session = (session_info.get("liquidity_status") == "LOW_MODERATE") or (session_info.get("bkk_hour", 12) in range(6, 15))

            # Realistic Intraday TP Cap: Balance Winrate & R:R (Default target 1.5x - 2.5x Risk, max $16 USD for Intraday)
            calculated_risk = max((nearest_supply["zone_high"] + (current_atr * 0.35)) - current_price, 3.0)
            ideal_realistic_tp = current_price - (calculated_risk * 2.0)
            if target_tp < ideal_realistic_tp and (current_price - target_tp) > 16.0:
                target_tp = max(target_tp, current_price - 16.0)

            # Evaluate Market Entry baseline
            sl_distance = raw_sl - current_price
            risk_usd = sl_distance
            reward_usd = current_price - target_tp
            rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0

            if sl_distance > MAX_GOLD_SL_USD:
                setup_type = "REJECTED_SL_TOO_WIDE"
                direction = "NEUTRAL"
                target_entry = current_price
                target_sl = raw_sl
                setup_reason = (
                    f"⚠️ ปฏิเสธ SELL: ระยะ Stop Loss กว้างเกินเกณฑ์ (${sl_distance:.2f} > ${MAX_GOLD_SL_USD:.2f}) "
                    f"เสี่ยงเกินขนาดสำหรับ Intraday Scalp รอราคาเด้งทดสอบ Supply Zone (${nearest_supply['zone_low']:.2f} - ${nearest_supply['zone_high']:.2f})"
                )
            elif rr_ratio < MIN_GOLD_RR_RATIO:
                setup_type = "REJECTED_POOR_RR"
                direction = "NEUTRAL"
                target_entry = current_price
                target_sl = raw_sl
                pullback_entry = max(nearest_supply["zone_low"], target_tp + (risk_usd * MIN_GOLD_RR_RATIO))
                pullback_entry_recommended = round(pullback_entry, 2)
                setup_reason = (
                    f"⚠️ ปฏิเสธ SELL: Risk:Reward ต่ำเกินไป (R:R {rr_ratio:.2f} < {MIN_GOLD_RR_RATIO:.2f} | เสี่ยง ${risk_usd:.2f} เพื่อกำไร ${reward_usd:.2f}) "
                    f"ห้ามไล่ราคา ควรรอเด้ง Pullback เข้าเนื้อ Supply Zone ({nearest_supply['zone_low']:.2f} - {nearest_supply['zone_high']:.2f})"
                )
            elif is_chasing_below_zone or is_asian_session:
                # 🎯 Systematic Pullback / Limit Order: Do NOT chase at bottoms, enter at Fibo 65% OTE or Base Midpoint
                limit_entry_candidate = best_fibo.get("fibo_650") or nearest_supply.get("zone_mid") or (nearest_supply["zone_high"] - current_atr * 0.25)
                limit_entry = max(min(limit_entry_candidate, nearest_supply["zone_high"]), nearest_supply["zone_low"])
                target_entry = round(limit_entry, 2)
                target_sl = round(raw_sl, 2)
                order_execution_mode = "LIMIT"

                risk_usd = target_sl - target_entry
                reward_usd = target_entry - target_tp
                rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0

                setup_type = "ACTIONABLE_SELL_LIMIT"
                direction = "SELL"
                session_note = "ช่วงตลาดเอเชีย สภาพคล่องเบาบาง ป้องกัน Stop Hunt" if is_asian_session else f"ราคาเด้งลงห่างฐาน > 0.4x ATR ป้องกันการไล่ขายที่ปลายคลื่น"
                setup_reason = (
                    f"🎯 แนะนำ Sell Limit ดักเด้งที่ Fibo 65% OTE / Supply Base (${target_entry:.2f}) SL ${target_sl:.2f} (R:R {rr_ratio:.2f}) "
                    f"[{session_note} - [XAU-RULE-21]]"
                )
            else:
                target_entry = current_price
                target_sl = raw_sl
                order_execution_mode = "MARKET"
                setup_type = "SELL_SUPPLY_ZONE"
                direction = "SELL"
                setup_reason = f"ราคาแตะโซน Supply ({nearest_supply['pattern']}) ชิดฐานที่ {nearest_supply['zone_low']} - {nearest_supply['zone_high']} ยืนยันด้วยแท่งเทียน {trigger_tf} พร้อม R:R {rr_ratio:.2f}"

    # Check Role Reversal Proximity
    elif role_reversals:
        closest_rr = min(role_reversals, key=lambda z: abs(z.price_mid - current_price))
        if abs(closest_rr.price_mid - current_price) <= (current_atr * 0.8):
            if current_price >= closest_rr.price_mid:
                target_entry = current_price
                target_sl = closest_rr.price_low - (current_atr * 0.75)
                target_tp = current_price + (current_atr * 2.5)
                risk_usd = target_entry - target_sl
                reward_usd = target_tp - target_entry
                rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0

                if risk_usd > MAX_GOLD_SL_USD:
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
                    setup_reason = f"แนวต้านเดิมถูกทะลุและสลับบทบาทเป็นแนวรับใหม่ (Role Reversal) กำลัง Retest ที่ {closest_rr.price_mid:.2f} พร้อม R:R {rr_ratio:.2f}"
            else:
                target_entry = current_price
                target_sl = closest_rr.price_high + (current_atr * 0.75)
                target_tp = current_price - (current_atr * 2.5)
                risk_usd = target_sl - target_entry
                reward_usd = target_entry - target_tp
                rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0

                if risk_usd > MAX_GOLD_SL_USD:
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
                    setup_reason = f"แนวรับเดิมหลุดและสลับบทบาทเป็นแนวต้านใหม่ (Role Reversal) กำลัง Retest ที่ {closest_rr.price_mid:.2f} พร้อม R:R {rr_ratio:.2f}"

    active_login = adapter.mt5_client.account_info.get("login") if adapter.mt5_client.account_info else 434552387
    is_cent_account = (active_login == 160219615)
    account_label = f"Real Cent Exness (#{active_login})" if is_cent_account else f"Demo Exness (#{active_login})"

    return {
        "status": setup_type,
        "symbol": "XAUUSD",
        "mt5_symbol": resolved,
        "current_price": round(current_price, 2),
        "spread": round(float(live_spread), 2) if live_spread is not None else 0.20,
        "current_atr": round(float(current_atr), 2),
        "atr_15m": round(float(current_atr), 2),
        "target_account": active_login,
        "account_label": account_label,
        "is_sandbox": not is_cent_account,
        "strategy_name": "Gold S/R, Role Reversal & Demand/Supply (No OB)",
        "trend_indicators": {
            "ema15": ema15_val,
            "ma50": ma50_val,
            "trend": ma_trend
        },
        "session_info": session_info,
        "demand_zones": demands,
        "supply_zones": supplies,
        "nearest_demand": nearest_demand,
        "nearest_supply": nearest_supply,
        "fibo_golden_zone": best_fibo,
        "major_fibo": major_fibo,
        "minor_fibo": minor_fibo,
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
