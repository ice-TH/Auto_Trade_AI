from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
from src.data.base import Bar, TimeFrame
from src.analysis.swings import SwingPoint, detect_swings
from src.analysis.indicators import calculate_atr

@dataclass
class SRZone:
    zone_id: str
    symbol: str
    timeframe: TimeFrame
    zone_type: str  # "SUPPORT" or "RESISTANCE"
    price_high: float
    price_low: float
    price_mid: float
    touch_count: int = 0
    freshness: str = "FRESH"  # "FRESH", "TESTED", "EXHAUSTED"
    is_active: bool = True
    is_broken: bool = False
    is_role_reversed: bool = False
    is_locked: bool = False
    source: str = "AUTO_FRACTAL"  # "AUTO_FRACTAL" or "MANUAL"
    created_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    touches: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "zone_type": self.zone_type,
            "price_high": round(self.price_high, 2),
            "price_low": round(self.price_low, 2),
            "price_mid": round(self.price_mid, 2),
            "touch_count": self.touch_count,
            "freshness": self.freshness,
            "is_active": self.is_active,
            "is_broken": self.is_broken,
            "is_role_reversed": self.is_role_reversed,
            "is_locked": self.is_locked,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
        }

def build_sr_zones(
    symbol: str,
    bars: List[Bar],
    n_fractal: int = 3,
    atr_multiplier: float = 0.5
) -> List[SRZone]:
    """
    Construct Support & Resistance Zones using confirmed Pivot Fractals and Dynamic ATR width.
    """
    if len(bars) < (2 * n_fractal + 15):
        return []

    # Calculate ATR
    atr_series = calculate_atr(bars, period=14)
    current_atr = atr_series[-1]["value"] if atr_series else (bars[-1].close * 0.015)
    zone_half_width = (current_atr * atr_multiplier) / 2.0

    # Detect swings
    swings = detect_swings(bars, n=n_fractal)
    
    # Separate Highs and Lows
    high_swings = [s for s in swings if s.swing_type == "SWING_HIGH"]
    low_swings = [s for s in swings if s.swing_type == "SWING_LOW"]

    zones: List[SRZone] = []

    # Cluster Resistance Zones
    for s in high_swings:
        mid = s.price
        p_high = mid + zone_half_width
        p_low = mid - zone_half_width
        
        # Check if overlaps with existing resistance zone
        merged = False
        for z in zones:
            if z.zone_type == "RESISTANCE" and not (p_low > z.price_high or p_high < z.price_low):
                # Merge
                z.price_high = max(z.price_high, p_high)
                z.price_low = min(z.price_low, p_low)
                z.price_mid = (z.price_high + z.price_low) / 2.0
                merged = True
                break
                
        if not merged:
            zones.append(SRZone(
                zone_id=f"RES_{symbol}_{int(mid*100)}_{len(zones)}",
                symbol=symbol,
                timeframe=bars[0].timeframe,
                zone_type="RESISTANCE",
                price_high=p_high,
                price_low=p_low,
                price_mid=mid,
                source="AUTO_FRACTAL",
                created_at=s.bar_time,
                confirmed_at=s.confirmed_time
            ))

    # Cluster Support Zones
    for s in low_swings:
        mid = s.price
        p_high = mid + zone_half_width
        p_low = mid - zone_half_width
        
        merged = False
        for z in zones:
            if z.zone_type == "SUPPORT" and not (p_low > z.price_high or p_high < z.price_low):
                z.price_high = max(z.price_high, p_high)
                z.price_low = min(z.price_low, p_low)
                z.price_mid = (z.price_high + z.price_low) / 2.0
                merged = True
                break
                
        if not merged:
            zones.append(SRZone(
                zone_id=f"SUP_{symbol}_{int(mid*100)}_{len(zones)}",
                symbol=symbol,
                timeframe=bars[0].timeframe,
                zone_type="SUPPORT",
                price_high=p_high,
                price_low=p_low,
                price_mid=mid,
                source="AUTO_FRACTAL",
                created_at=s.bar_time,
                confirmed_at=s.confirmed_time
            ))

    # Evaluate Touches and Breaks against subsequent bars
    current_price = bars[-1].close
    break_buffer = current_atr * 0.4

    for z in zones:
        touches = 0
        is_broken = False
        reclaimed_after_break = False

        # Only evaluate bars AFTER the zone was confirmed
        for b in bars:
            if z.confirmed_at and b.open_time < z.confirmed_at:
                continue

            # Touch check (only count before permanent invalidation)
            if not reclaimed_after_break and b.high >= z.price_low and b.low <= z.price_high:
                touches += 1

            # Sequential Invalidation / Role Reversal lifecycle check
            if z.zone_type == "RESISTANCE":
                if not is_broken and b.close > (z.price_high + break_buffer):
                    is_broken = True  # Broken upward -> potential support role reversal
                elif is_broken and b.close < (z.price_low - break_buffer):
                    # Chopped back below after breakout -> zone is exhausted/whipsawed
                    reclaimed_after_break = True
            elif z.zone_type == "SUPPORT":
                if not is_broken and b.close < (z.price_low - break_buffer):
                    is_broken = True  # Broken downward -> potential resistance role reversal
                elif is_broken and b.close > (z.price_high + break_buffer):
                    # Chopped back above after breakdown -> zone is exhausted/whipsawed
                    reclaimed_after_break = True

        z.touch_count = touches
        z.is_broken = is_broken

        # Freshness rating
        if touches == 0:
            z.freshness = "FRESH"
        elif touches <= 2:
            z.freshness = "TESTED"
        else:
            z.freshness = "EXHAUSTED"

        # Check for clean role reversal (Broken once cleanly, never whipsawed back across)
        if reclaimed_after_break:
            z.is_active = False
            z.is_role_reversed = False
        elif is_broken:
            if z.zone_type == "RESISTANCE" and current_price >= z.price_low:
                z.is_role_reversed = True
            elif z.zone_type == "SUPPORT" and current_price <= z.price_high:
                z.is_role_reversed = True

    # Sort zones by proximity to current price
    zones.sort(key=lambda z: abs(z.price_mid - current_price))
    return zones
