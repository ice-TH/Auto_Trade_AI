"""
US Equities Swing Strategy (Magnificent 7: AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA).
Applies Price Action Demand/Supply (Base Retest) and Headroom Guard to Day/H4 Timeframes,
with Dynamic ATR-based Stop Loss, Swing Holding, and Earnings Blackout Guard.
Enforces [EQ-RULE-01] to [EQ-RULE-07].
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from src.data.base import TimeFrame, Bar
from src.data.mt5_adapter import MT5DataAdapter
from src.analysis.indicators import calculate_atr, calculate_ema
from src.analysis.gold_strategy import detect_demand_supply_zones
from src.risk.earnings_guard import is_near_earnings, clean_symbol

logger = logging.getLogger(__name__)

SUPPORTED_US_EQUITIES = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
MIN_EQUITY_RR_RATIO = 2.0  # Swing trading requires minimum 1:2 R:R

def scan_equity_setup(
    symbol: str = "AAPL",
    adapter: Optional[MT5DataAdapter] = None
) -> Dict[str, Any]:
    """
    Scan a US Equity CFD on Daily and H4 timeframes for Demand Base Retest Swing setups.
    """
    clean_sym = clean_symbol(symbol)
    data_adapter = adapter or MT5DataAdapter()
    if hasattr(data_adapter, "_ensure_connected"):
        data_adapter._ensure_connected()

    # 1. Check Earnings Blackout Guard
    near_earnings, earnings_reason = is_near_earnings(clean_sym)
    if near_earnings:
        return {
            "symbol": clean_sym,
            "status": "REJECTED_EARNINGS",
            "recommended_direction": "NEUTRAL",
            "setup_reason": earnings_reason,
            "order_block_excluded": True,
            "strategy_type": "SWING_BASE_RETEST",
            "requires_approval": True,
        }

    # 2. Fetch Day bars for Macro Trend & Structure
    bars_day = data_adapter.get_bars(symbol, TimeFrame.DAY, limit=60)
    if not bars_day or len(bars_day) < 15:
        # Fallback to H1/M15 if Day is not loaded
        bars_day = data_adapter.get_bars(symbol, TimeFrame.H1, limit=60)
        if not bars_day or len(bars_day) < 15:
            return {
                "symbol": clean_sym,
                "status": "INSUFFICIENT_DATA",
                "recommended_direction": "NEUTRAL",
                "setup_reason": f"ข้อมูลกราฟแท่งเทียนของ {clean_sym} ไม่เพียงพอสำหรับการวิเคราะห์ Day/H4",
                "requires_approval": True,
            }

    current_price = bars_day[-1].close
    
    # Calculate Day ATR for dynamic volatility-based stop loss
    atr_series = calculate_atr(bars_day, period=14)
    current_atr = atr_series[-1]["value"] if atr_series else (current_price * 0.02)
    current_atr = max(current_atr, current_price * 0.01)  # Minimum 1% floor

    # Calculate Moving Averages on Day timeframe for Trend Alignment [EQ-RULE-01]
    ema_20 = calculate_ema(bars_day, period=20)
    ema_50 = calculate_ema(bars_day, period=50)
    val_ema20 = ema_20[-1]["value"] if ema_20 else current_price
    val_ema50 = ema_50[-1]["value"] if ema_50 else (current_price * 0.98)
    is_macro_bullish = val_ema20 >= val_ema50

    # 3. Detect Pure Price Action Demand & Supply Zones on Daily/H4 structure
    ds_zones = detect_demand_supply_zones(bars_day, min_bars=10)
    demands = sorted(ds_zones.get("demand_zones", []), key=lambda z: abs(current_price - z["zone_high"]))
    supplies = sorted(ds_zones.get("supply_zones", []), key=lambda z: abs(current_price - z["zone_low"]))

    nearest_demand = demands[0] if demands else None
    nearest_supply = supplies[0] if supplies else None

    # Check Headroom to Overhead Supply [EQ-RULE-05]
    overhead_supplies = [s for s in supplies if s["zone_low"] > current_price]
    nearest_overhead = overhead_supplies[0] if overhead_supplies else None
    headroom = (nearest_overhead["zone_low"] - current_price) if nearest_overhead else 999.0

    # 4. Check Demand Zone Proximity & Base Retest
    # In Swing stocks, price touches or is within 0.5x ATR_Day of Demand Base
    is_at_demand = (
        nearest_demand is not None
        and (current_price <= nearest_demand["zone_high"] + (current_atr * 0.50))
        and (current_price >= nearest_demand["zone_low"] - (current_atr * 0.35))
    )

    if not is_macro_bullish:
        return {
            "symbol": clean_sym,
            "status": "REJECTED_TREND_BEARISH",
            "recommended_direction": "NEUTRAL",
            "current_price": current_price,
            "current_atr": round(current_atr, 2),
            "setup_reason": f"⚠️ ปฏิเสธ BUY: แนวโน้มใหญ่ของ {clean_sym} เป็น Bearish (EMA20 {val_ema20:.2f} < EMA50 {val_ema50:.2f}) ห้ามเทรดสวนแนวโน้มใหญ่ [EQ-RULE-01]",
            "requires_approval": True,
        }

    if is_at_demand:
        # Headroom Guard Check [EQ-RULE-05]
        if headroom < (current_atr * 1.5):
            return {
                "symbol": clean_sym,
                "status": "REJECTED_NEAR_RESISTANCE",
                "recommended_direction": "NEUTRAL",
                "current_price": current_price,
                "current_atr": round(current_atr, 2),
                "setup_reason": f"⚠️ ปฏิเสธ BUY: ราคาใกล้แนวต้าน Supply ({nearest_overhead['zone_low']:.2f}) มากเกินไป (Headroom {headroom:.2f} < 1.5x ATR) ห้ามซื้อชิดแนวต้าน [EQ-RULE-05]",
                "requires_approval": True,
            }

        # Dynamic ATR-based Stop Loss below base [EQ-RULE-06]
        # Entry at Discount: zone_mid or current_price
        target_entry = round(current_price, 2)
        target_sl = round(nearest_demand["zone_low"] - (current_atr * 0.50), 2)
        
        # Target TP at nearest overhead supply or minimum 2x ATR
        if nearest_overhead:
            target_tp = round(nearest_overhead["zone_low"] - (current_atr * 0.25), 2)
        else:
            target_tp = round(target_entry + (current_atr * 3.0), 2)

        risk_usd = target_entry - target_sl
        reward_usd = target_tp - target_entry
        rr_ratio = (reward_usd / risk_usd) if risk_usd > 0 else 0.0

        if rr_ratio < MIN_EQUITY_RR_RATIO:
            return {
                "symbol": clean_sym,
                "status": "REJECTED_POOR_RR",
                "recommended_direction": "NEUTRAL",
                "current_price": current_price,
                "current_atr": round(current_atr, 2),
                "rr_ratio": round(rr_ratio, 2),
                "setup_reason": f"⚠️ ปฏิเสธ BUY: Risk:Reward {rr_ratio:.2f} ต่ำกว่าเกณฑ์ขั้นต่ำ {MIN_EQUITY_RR_RATIO:.2f}",
                "requires_approval": True,
            }

        return {
            "symbol": clean_sym,
            "status": "BUY_PULLBACK_BASE",
            "recommended_direction": "BUY",
            "current_price": current_price,
            "current_atr": round(current_atr, 2),
            "target_entry": target_entry,
            "target_sl": target_sl,
            "target_tp": target_tp,
            "risk_usd": round(risk_usd, 2),
            "reward_usd": round(reward_usd, 2),
            "rr_ratio": round(rr_ratio, 2),
            "nearest_demand": nearest_demand,
            "nearest_supply": nearest_overhead,
            "holding_type": "SWING_HOLDING_ALLOWED",
            "setup_reason": (
                f"✅ หุ้น {clean_sym} เกิดจังหวะ Pullback ทดสอบฐาน Demand Base ({nearest_demand['pattern']}) "
                f"ที่ {nearest_demand['zone_low']:.2f} - {nearest_demand['zone_high']:.2f} "
                f"พร้อม R:R {rr_ratio:.2f} (SL: ${target_sl:.2f}, TP: ${target_tp:.2f}) [EQ-RULE-04]"
            ),
            "requires_approval": True,
            "order_block_excluded": True,
        }

    return {
        "symbol": clean_sym,
        "status": "WAITING_FOR_BASE",
        "recommended_direction": "NEUTRAL",
        "current_price": current_price,
        "current_atr": round(current_atr, 2),
        "setup_reason": f"หุ้น {clean_sym} กำลังเคลื่อนไหวปกติ ยังไม่ย่อตัวเข้าใกล้ฐาน Demand Base ที่น่าสนใจ รอจังหวะพักตัว",
        "requires_approval": True,
        "order_block_excluded": True,
    }
