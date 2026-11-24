from typing import List, Dict, Any, Optional
from src.data.base import Bar
from src.analysis.swings import SwingPoint
from src.analysis.indicators import calculate_atr

def calculate_fibonacci_levels(
    symbol: str,
    bars: List[Bar],
    swings: List[SwingPoint]
) -> Optional[Dict[str, Any]]:
    """
    Calculate Fibonacci Retracement levels from the most recent major swing high and swing low.
    Records anchor timestamps, prices, direction, and retracement levels.
    """
    if len(swings) < 2:
        return None

    # Get the latest significant high and low
    recent_highs = [s for s in swings if s.swing_type == "SWING_HIGH"]
    recent_lows = [s for s in swings if s.swing_type == "SWING_LOW"]

    if not recent_highs or not recent_lows:
        return None

    last_high = recent_highs[-1]
    last_low = recent_lows[-1]

    # Determine trend direction from which swing came first
    if last_low.bar_time < last_high.bar_time:
        # Upward leg: Retracement downwards from High to Low
        direction = "UP"
        start_swing = last_low
        end_swing = last_high
        diff = last_high.price - last_low.price
        levels = {
            "0.0": round(last_high.price, 2),
            "0.236": round(last_high.price - (0.236 * diff), 2),
            "0.382": round(last_high.price - (0.382 * diff), 2),
            "0.500": round(last_high.price - (0.500 * diff), 2),
            "0.618": round(last_high.price - (0.618 * diff), 2),
            "0.786": round(last_high.price - (0.786 * diff), 2),
            "1.0": round(last_low.price, 2),
        }
    else:
        # Downward leg: Retracement upwards from Low to High
        direction = "DOWN"
        start_swing = last_high
        end_swing = last_low
        diff = last_high.price - last_low.price
        levels = {
            "0.0": round(last_low.price, 2),
            "0.236": round(last_low.price + (0.236 * diff), 2),
            "0.382": round(last_low.price + (0.382 * diff), 2),
            "0.500": round(last_low.price + (0.500 * diff), 2),
            "0.618": round(last_low.price + (0.618 * diff), 2),
            "0.786": round(last_low.price + (0.786 * diff), 2),
            "1.0": round(last_high.price, 2),
        }

    return {
        "symbol": symbol,
        "direction": direction,
        "start": {
            "time": start_swing.bar_time.isoformat(),
            "price": round(start_swing.price, 2),
            "type": start_swing.swing_type
        },
        "end": {
            "time": end_swing.bar_time.isoformat(),
            "price": round(end_swing.price, 2),
            "type": end_swing.swing_type
        },
        "levels": levels
    }

def detect_demand_supply_zones(bars: List[Bar], atr_threshold: float = 1.3) -> List[Dict[str, Any]]:
    """
    Detect Demand (Rally-Base-Rally or Drop-Base-Rally) and
    Supply (Drop-Base-Drop or Rally-Base-Drop) imbalance zones.
    """
    zones: List[Dict[str, Any]] = []
    if len(bars) < 20:
        return zones

    atr_data = calculate_atr(bars, period=14)
    current_atr = atr_data[-1]["value"] if atr_data else (bars[-1].close * 0.015)

    for i in range(1, len(bars) - 1):
        prev_bar = bars[i - 1]
        base_bar = bars[i]
        departure_bar = bars[i + 1]

        body = abs(departure_bar.close - departure_bar.open)
        # Check if departure has strong imbalance
        if body > (current_atr * atr_threshold):
            if departure_bar.close > departure_bar.open:
                # Bullish departure -> Demand Zone at base
                zones.append({
                    "id": f"DEMAND_{bars[0].symbol}_{i}",
                    "type": "DEMAND",
                    "price_high": round(max(base_bar.open, base_bar.close), 2),
                    "price_low": round(base_bar.low, 2),
                    "base_time": base_bar.open_time.isoformat(),
                    "departure_time": departure_bar.open_time.isoformat(),
                    "strength": round(body / current_atr, 2)
                })
            else:
                # Bearish departure -> Supply Zone at base
                zones.append({
                    "id": f"SUPPLY_{bars[0].symbol}_{i}",
                    "type": "SUPPLY",
                    "price_high": round(base_bar.high, 2),
                    "price_low": round(min(base_bar.open, base_bar.close), 2),
                    "base_time": base_bar.open_time.isoformat(),
                    "departure_time": departure_bar.open_time.isoformat(),
                    "strength": round(body / current_atr, 2)
                })

    return zones[-6:] # Keep most recent 6 zones
