from typing import List, Dict, Any, Optional
from src.data.base import Bar
from src.analysis.zones import SRZone
from src.analysis.indicators import calculate_ema, calculate_atr
from src.strategy.plans import TradingPlan

def analyze_market_narrative(
    symbol: str,
    bars_week: List[Bar],
    bars_day: List[Bar],
    zones: List[SRZone],
    plan: Optional[TradingPlan] = None
) -> Dict[str, Any]:
    """
    Hybrid AI Trend & Strategy Narrative Analyzer.
    Runs 100% locally and deterministically without external dependencies.
    Provides structured qualitative breakdown across 4 analytical dimensions.
    """
    if not bars_day:
        return {"error": "No market data available for AI analysis"}

    current_price = bars_day[-1].close
    atr_data = calculate_atr(bars_day, period=14)
    atr = atr_data[-1]["value"] if atr_data else (current_price * 0.015)

    # 1. Macro / WEEK Context
    week_insight = "แนวโน้มภาพใหญ่ระดับสัปดาห์ (WEEK): อยู่ในช่วงไซด์เวย์พักตัวในกรอบกลาง"
    if bars_week and len(bars_week) >= 50:
        ema50 = calculate_ema(bars_week, 50)
        if ema50:
            val50 = ema50[-1]["value"]
            if current_price > val50:
                week_insight = f"แนวโน้มภาพใหญ่ระดับสัปดาห์ (WEEK): ขาขึ้นแข็งแกร่ง (BULLISH) ราคายืนเหนือเส้น EMA 50 Week (${val50:.2f}) รักษาโมเมนตัมบวกระยะยาวได้ดี"
            else:
                week_insight = f"แนวโน้มภาพใหญ่ระดับสัปดาห์ (WEEK): ระมัดระวัง/ขาลง (BEARISH) ราคาอยู่ใต้เส้น EMA 50 Week (${val50:.2f}) กองทุนใหญ่ยังชะลอการซื้อ"

    # 2. DAY Structure & Key Zones
    supports = [z for z in zones if z.zone_type == "SUPPORT" and not z.is_broken]
    resistances = [z for z in zones if z.zone_type == "RESISTANCE" and not z.is_broken]

    nearest_sup = min(supports, key=lambda z: abs(z.price_mid - current_price)) if supports else None
    nearest_res = min(resistances, key=lambda z: abs(z.price_mid - current_price)) if resistances else None

    structure_insight = "โครงสร้างราคาระดับวัน: ราคากำลังแกว่งตัวอยู่ในกรอบแนวรับ-แนวต้านแนวนอน"
    if nearest_sup and nearest_res:
        fresh_th = "โซนใหม่สด" if nearest_sup.freshness == "FRESH" else "โซนถูกทดสอบแล้ว"
        structure_insight = (
            f"โครงสร้างราคาระดับวัน (DAY): มีแนวรับสำคัญที่ ${nearest_sup.price_low:.2f} - ${nearest_sup.price_high:.2f} "
            f"({fresh_th}, ถูกทดสอบแล้ว {nearest_sup.touch_count} ครั้ง) และมีแนวต้านดักอยู่ด้านบนที่ "
            f"${nearest_res.price_low:.2f} - ${nearest_res.price_high:.2f}"
        )

    # 3. Headroom & Resistance Proximity
    headroom_insight = "พื้นที่วิ่งด้านบนเปิดกว้าง มีระยะทำกำไรได้ดี"
    if nearest_res and nearest_res.price_low > current_price:
        headroom = nearest_res.price_low - current_price
        headroom_atr = headroom / atr
        if headroom_atr < 1.0:
            headroom_insight = (
                f"⚠️ คำเตือนเรื่องระยะวิ่ง (Headroom): แนวต้านดักอยู่ใกล้มาก (ห่างเพียง ${headroom:.2f} หรือ {headroom_atr:.1f}x ของ ATR) "
                f"พื้นที่ทำกำไรแคบเกินไป เสี่ยงโดนชนแนวต้านแล้วดีดกลับ ไม่อนุญาตให้เปิด Buy บริเวณนี้"
            )
        else:
            headroom_insight = (
                f"✅ พื้นที่วิ่งด้านบนเปิดโล่ง: ระยะห่างถึงแนวต้านใหญ่อยู่ที่ ${headroom:.2f} ({headroom_atr:.1f}x ของ ATR) "
                f"ไม่มีสิ่งกีดขวางแนวต้านขวางหน้าในระยะใกล้ สภาพคล่องพร้อมวิ่ง"
            )

    # 4. Actionable Verdict & Money Management Summary
    verdict = "สถานะ: เฝ้าติดตามอย่างต่อเนื่อง รอสัญญาณแท่งเทียนยืนยันในโซนสำคัญ"
    if plan:
        if plan.status.value == "READY_FOR_REVIEW":
            verdict = (
                f"🎯 แผนพร้อมเข้าเทรด (ผ่านเงื่อนไขครบถ้วน): เกิดการเด้งตัวที่แนวรับ DAY ชัดเจน "
                f"เป้าหมายกำไร TP ที่ ${plan.take_profit:.2f} | จุดตัดขาดทุน SL ที่ ${plan.stop_loss:.2f} (R:R {plan.risk_reward_ratio:.2f}) "
                f"ขนาดคำสั่งแนะนำ: {plan.lot_size} Lot ปลอดภัยภายใต้เพดาน Leverage 1:5"
            )
        elif plan.status.value == "REJECTED_NO_TRADE":
            verdict = f"🛑 วินัยการเทรด: ปฏิเสธการเข้าเทรด เหตุผล: {plan.rejection_reason}"
        elif plan.status.value == "WAITING_CONDITIONS":
            verdict = f"⏳ กำลังรอจังหวะ: ราคา (${current_price:.2f}) {plan.rejection_reason or 'ยังไม่อยู่ในโซนแนวรับที่ได้เปรียบ ให้รอราคาย่อตัวลงมาทดสอบโซนก่อน'}"

    return {
        "symbol": symbol,
        "macro_week_insight": week_insight,
        "day_structure_insight": structure_insight,
        "headroom_insight": headroom_insight,
        "actionable_verdict": verdict,
        "current_price": round(current_price, 2),
        "atr_14": round(atr, 2),
        "plan_status": plan.status.value if plan else "NO_PLAN"
    }

def generate_antigravity_prompt_context(
    symbol: str,
    bars_day: List[Bar],
    zones: List[SRZone],
    plan: Optional[TradingPlan] = None
) -> str:
    """Generate clean, structured context for the user to copy/paste directly to Antigravity."""
    curr_price = bars_day[-1].close if bars_day else 0.0
    text = [
        f"### AUTOTRADE MARKET CONTEXT FOR {symbol}",
        f"- Current Price: ${curr_price:.2f}",
        f"- Active Support Zones: {', '.join(f'${z.price_low:.2f}-${z.price_high:.2f}' for z in zones if z.zone_type == 'SUPPORT')[:100]}",
        f"- Active Resistance Zones: {', '.join(f'${z.price_low:.2f}-${z.price_high:.2f}' for z in zones if z.zone_type == 'RESISTANCE')[:100]}",
    ]
    if plan:
        text.append(f"- Current Plan Status: {plan.status.value}")
        text.append(f"- Plan Entry: ${plan.entry_price:.2f} | SL: ${plan.stop_loss:.2f} | TP: ${plan.take_profit:.2f}")
        text.append(f"- Risk/Reward: {plan.risk_reward_ratio:.2f} | Lot Size: {plan.lot_size}")
        if plan.rejection_reason:
            text.append(f"- Rejection Note: {plan.rejection_reason}")
    text.append("\nAntigravity, please evaluate this technical structure, headroom, and risk parameters.")
    return "\n".join(text)
