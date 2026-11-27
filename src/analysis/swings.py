from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from src.data.base import Bar

@dataclass
class SwingPoint:
    index: int
    bar_time: datetime
    confirmed_time: datetime
    price: float
    swing_type: str  # "SWING_HIGH" or "SWING_LOW"
    is_major: bool = False

def detect_swings(bars: List[Bar], n: int = 3) -> List[SwingPoint]:
    """
    Detect Pivot Fractal Swings with N bars left and N bars right.
    Strictly zero look-ahead bias: A swing at bar index i is only confirmed
    and visible to the system at the close of bar index i + n.
    """
    swings: List[SwingPoint] = []
    total_bars = len(bars)
    if total_bars < (2 * n + 1):
        return swings

    for i in range(n, total_bars - n):
        curr_high = bars[i].high
        curr_low = bars[i].low

        # Check Swing High
        is_high = True
        for k in range(1, n + 1):
            if bars[i - k].high >= curr_high or bars[i + k].high > curr_high:
                is_high = False
                break
        if is_high:
            swings.append(SwingPoint(
                index=i,
                bar_time=bars[i].open_time,
                confirmed_time=bars[i + n].close_time,
                price=curr_high,
                swing_type="SWING_HIGH"
            ))

        # Check Swing Low
        is_low = True
        for k in range(1, n + 1):
            if bars[i - k].low <= curr_low or bars[i + k].low < curr_low:
                is_low = False
                break
        if is_low:
            swings.append(SwingPoint(
                index=i,
                bar_time=bars[i].open_time,
                confirmed_time=bars[i + n].close_time,
                price=curr_low,
                swing_type="SWING_LOW"
            ))

    swings.sort(key=lambda s: s.confirmed_time)
    return swings


def analyze_market_structure(bars: List[Bar], n_fractal: int = 3) -> Dict[str, Any]:
    """
    Zero-look-ahead Swing Market Structure analyzer (HH/HL/LH/LL + live BOS/CHoCH).
    Uses confirmed pivot swings (n_fractal bars left/right) plus the latest closed bar
    to detect immediate BOS/CHoCH structure shifts without repainting or look-ahead bias.
    """
    if len(bars) < (2 * n_fractal + 5):
        return {
            "bias": "NEUTRAL",
            "swing_bias": "NEUTRAL",
            "pattern": "INSUFFICIENT",
            "live_break": "NONE",
            "last_sh": None,
            "last_sl": None,
        }

    swings = detect_swings(bars, n=n_fractal)
    shs = [s for s in swings if s.swing_type == "SWING_HIGH"]
    sls = [s for s in swings if s.swing_type == "SWING_LOW"]

    if len(shs) < 2 or len(sls) < 2:
        return {
            "bias": "NEUTRAL",
            "swing_bias": "NEUTRAL",
            "pattern": "INSUFFICIENT",
            "live_break": "NONE",
            "last_sh": round(shs[-1].price, 2) if shs else None,
            "last_sl": round(sls[-1].price, 2) if sls else None,
        }

    prev_sh, last_sh = shs[-2], shs[-1]
    prev_sl, last_sl = sls[-2], sls[-1]

    high_tag = "HH" if last_sh.price > prev_sh.price else "LH"
    low_tag = "HL" if last_sl.price > prev_sl.price else "LL"
    pattern = f"{high_tag}/{low_tag}"

    if high_tag == "HH" and low_tag == "HL":
        swing_bias = "BULLISH"
    elif high_tag == "LH" and low_tag == "LL":
        swing_bias = "BEARISH"
    else:
        swing_bias = "MIXED"

    curr_close = bars[-1].close
    live_break = "NONE"
    if curr_close > last_sh.price:
        live_break = "CHOCH_BULL" if swing_bias == "BEARISH" else "BOS_BULL"
    elif curr_close < last_sl.price:
        live_break = "CHOCH_BEAR" if swing_bias == "BULLISH" else "BOS_BEAR"

    if live_break in ("BOS_BULL", "CHOCH_BULL"):
        effective_bias = "BULLISH"
    elif live_break in ("BOS_BEAR", "CHOCH_BEAR"):
        effective_bias = "BEARISH"
    else:
        effective_bias = swing_bias

    return {
        "bias": effective_bias,
        "swing_bias": swing_bias,
        "pattern": pattern,
        "live_break": live_break,
        "last_sh": round(last_sh.price, 2),
        "last_sl": round(last_sl.price, 2),
    }
