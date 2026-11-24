from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
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
