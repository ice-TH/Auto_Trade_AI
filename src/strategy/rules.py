from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from src.data.base import Bar, TimeFrame
from src.analysis.zones import SRZone
from src.analysis.indicators import calculate_ema, calculate_atr, calculate_volume_ma
from src.risk.sizing import calculate_position_size
from src.strategy.plans import TradingPlan, PlanStatus
from config.settings import Settings

def evaluate_bounce_setup(
    symbol: str,
    bars_week: List[Bar],
    bars_day: List[Bar],
    bars_m15: List[Bar],
    zones_day: List[SRZone],
    settings: Settings,
    allow_short: bool = False
) -> TradingPlan:
    """
    Evaluate deterministic Support Bounce strategy adhering to user-agreed constraints:
    - Never buy near resistance (Headroom & Proximity Guard)
    - Validates WEEK trend context
    - M15 reversal candle confirmation
    - Sizing capped strictly at 1:5 leverage & 3,000 THB capital
    """
    now_utc = datetime.now(timezone.utc)
    plan_id = f"PLAN_{symbol}_{int(now_utc.timestamp())}"
    
    if not bars_day or len(bars_day) < 30:
        plan = TradingPlan(plan_id=plan_id, symbol=symbol, status=PlanStatus.REJECTED_NO_TRADE)
        plan.rejection_reason = "Insufficient historical DAY bars for analysis."
        return plan

    current_price = bars_day[-1].close
    atr_series = calculate_atr(bars_day, period=14)
    current_atr = atr_series[-1]["value"] if atr_series else (current_price * 0.015)

    # 1. Determine WEEK Trend Context
    week_trend = "NEUTRAL"
    if bars_week and len(bars_week) >= 50:
        ema50_w = calculate_ema(bars_week, 50)
        ema200_w = calculate_ema(bars_week, 200) if len(bars_week) >= 200 else []
        if ema50_w:
            latest_ema50 = ema50_w[-1]["value"]
            if bars_week[-1].close > latest_ema50:
                week_trend = "BULLISH"
            else:
                week_trend = "BEARISH"

    # 2. Find Key Active Support and Resistance Zones
    support_zones = [z for z in zones_day if z.zone_type == "SUPPORT" and not z.is_broken]
    resistance_zones = [z for z in zones_day if z.zone_type == "RESISTANCE" and not z.is_broken]

    # Find closest support zone below or at current price
    valid_supports = [z for z in support_zones if z.price_high >= (current_price - current_atr * 0.8)]
    # Find closest overhead resistance zone above current price
    overhead_resistances = [z for z in resistance_zones if z.price_low > current_price]
    overhead_resistances.sort(key=lambda z: z.price_low)

    target_resistance = overhead_resistances[0] if overhead_resistances else None

    # Base Plan Skeleton
    plan = TradingPlan(
        plan_id=plan_id,
        symbol=symbol,
        direction="LONG",
        week_trend=week_trend,
        created_at=now_utc
    )

    if not valid_supports:
        plan.status = PlanStatus.WAITING_CONDITIONS
        plan.rejection_reason = f"Price (${current_price:.2f}) is not near any valid DAY Support Zone. Waiting for pullback."
        return plan

    target_support = valid_supports[0]
    plan.day_zone_id = target_support.zone_id
    plan.day_zone_low = target_support.price_low
    plan.day_zone_high = target_support.price_high

    # 3. CRITICAL: Proximity & Headroom Guard (กฎห้ามซื้อติดแนวต้าน)
    if target_resistance:
        headroom = target_resistance.price_low - current_price
        plan.headroom_to_resistance = headroom
        min_required_headroom = current_atr * 1.0 # Must have at least 1.0 ATR distance to resistance!
        
        if headroom < min_required_headroom:
            plan.status = PlanStatus.REJECTED_NO_TRADE
            plan.rejection_reason = (
                f"REJECTED: Overhead Resistance Zone at ${target_resistance.price_low:.2f} is too close "
                f"(Headroom: ${headroom:.2f} < required 1.0 ATR ${min_required_headroom:.2f}). "
                f"Buying into resistance is strictly forbidden."
            )
            return plan
    else:
        # No immediate resistance above -> generous headroom estimate
        plan.headroom_to_resistance = current_atr * 3.0

    # 4. Check M15 Trigger Confirmation
    # Does M15 show a reversal candle?
    has_m15_trigger = False
    if bars_m15 and len(bars_m15) >= 5:
        last_m15 = bars_m15[-1]
        m15_vol_ma = calculate_volume_ma(bars_m15, period=20)
        avg_vol = m15_vol_ma[-1]["value"] if m15_vol_ma else 50000.0

        candle_range = max(last_m15.high - last_m15.low, 0.001)
        lower_wick = min(last_m15.open, last_m15.close) - last_m15.low
        is_bullish_close = last_m15.close >= last_m15.open
        is_pinbar = (lower_wick / candle_range) >= 0.40 # Long lower wick
        has_volume = last_m15.volume >= (avg_vol * 0.7)

        if (is_bullish_close or is_pinbar) and has_volume:
            has_m15_trigger = True

    # 5. Determine Entry, Stop Loss, and Take Profit
    entry_price = current_price
    sl_buffer = current_atr * 0.35 # Volatility buffer behind support
    stop_loss = round(target_support.price_low - sl_buffer, 2)

    if target_resistance:
        tp_buffer = current_atr * 0.2
        take_profit = round(target_resistance.price_low - tp_buffer, 2)
    else:
        take_profit = round(entry_price + (current_atr * 2.5), 2)

    sl_dist = entry_price - stop_loss
    tp_dist = take_profit - entry_price
    rr_ratio = tp_dist / max(sl_dist, 0.01)

    plan.entry_price = entry_price
    plan.stop_loss = stop_loss
    plan.take_profit = take_profit
    plan.risk_reward_ratio = rr_ratio

    # Check R:R ratio
    if rr_ratio < 1.2:
        plan.status = PlanStatus.REJECTED_NO_TRADE
        plan.rejection_reason = f"REJECTED: Risk-Reward ratio ({rr_ratio:.2f}) is below 1.2 minimum threshold."
        return plan

    # 6. Money Management & Sizing Calculation
    sizing = calculate_position_size(
        symbol=symbol,
        capital_thb=settings.base_capital_thb,
        entry_price=entry_price,
        stop_loss_price=stop_loss,
        risk_percent=settings.risk_per_trade_percent,
        max_leverage=settings.max_leverage
    )

    if sizing["status"] == "NO_TRADE":
        plan.status = PlanStatus.REJECTED_NO_TRADE
        plan.rejection_reason = f"REJECTED: Money Management constraint -> {sizing['reason']}"
        return plan

    plan.shares = sizing["shares"]
    plan.lot_size = sizing["lot_size"]
    plan.risk_thb = sizing["risk_thb"]
    plan.notional_thb = sizing["notional_thb"]
    plan.effective_leverage = sizing["effective_leverage"]

    # 7. Final State Assignment
    if has_m15_trigger:
        plan.status = PlanStatus.READY_FOR_REVIEW
        plan.notes = "Setup confirmed by DAY Support Zone bounce + M15 reversal candle with volume support."
    else:
        plan.status = PlanStatus.WAITING_CONDITIONS
        plan.notes = "DAY Support Zone touched. Waiting for M15 reversal candle confirmation."

    return plan
