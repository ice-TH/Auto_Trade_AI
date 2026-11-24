from datetime import datetime, time, timezone, timedelta
from typing import Tuple, Dict, Any, Optional
from zoneinfo import ZoneInfo
import logging

logger = logging.getLogger(__name__)

TZ_UTC = timezone.utc
TZ_BANGKOK = ZoneInfo("Asia/Bangkok")
TZ_EASTERN = ZoneInfo("America/New_York")

# Standard High-Impact US Macro News Release Times (in Bangkok Time UTC+7)
# 1. 19:30 - 20:30 BKK: CPI, PPI, Non-Farm Payrolls, GDP, Retail Sales, Unemployment Claims
# 2. 21:00 - 22:00 BKK: ISM Manufacturing/Services, Consumer Sentiment, New Home Sales
# 3. 01:00 - 02:30 BKK: FOMC Interest Rate Decision, Fed Chair Powell Press Conference
HIGH_IMPACT_NEWS_WINDOWS_BKK = [
    # (start_time, end_time, description)
    (time(19, 15), time(20, 45), "US Morning Data / CPI / NFP / PPI"),
    (time(20, 45), time(22, 15), "ISM / PMI / Consumer Confidence"),
    (time(0, 45), time(2, 30), "FOMC Rate Decision / Fed Statements"),
]

def to_bangkok(dt: datetime) -> datetime:
    """Convert any aware or naive datetime to Asia/Bangkok time (UTC+7)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_UTC)
    return dt.astimezone(TZ_BANGKOK)

def is_news_blackout(dt: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    Check if the given time falls inside a high-impact US macro news blackout window.
    During news blackout windows, all Pending Orders must be cancelled and no new limits placed.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    
    dt_bkk = to_bangkok(dt)
    # Check weekday (Monday=0 to Friday=4). Markets closed or quiet on weekends
    if dt_bkk.weekday() >= 5:
        return False, "Weekend: Regular market closed"

    current_t = dt_bkk.time()

    for start_t, end_t, desc in HIGH_IMPACT_NEWS_WINDOWS_BKK:
        if start_t <= end_t:
            if start_t <= current_t <= end_t:
                return True, f"⚠️ NEWS BLACKOUT: อยู่ในช่วงข่าวแรงสหรัฐฯ ({desc}) ห้ามวาง Limit Order [XAU-RULE-17]"
        else:
            # Over midnight window (e.g. 23:45 to 02:30)
            if current_t >= start_t or current_t <= end_t:
                return True, f"⚠️ NEWS BLACKOUT: อยู่ในช่วงข่าวแรงสหรัฐฯ ({desc}) ห้ามวาง Limit Order [XAU-RULE-17]"

    return False, "สภาวะเวลาปกติ: ปลอดภัยจากหน้าต่างข่าวแรงตามตาราง"

def is_spread_acceptable(spread: float, max_allowed_spread: float = 0.40) -> Tuple[bool, str]:
    """
    Ensure the current broker spread on gold does not exceed the allowed threshold.
    Normal Exness standard/pro gold spread is approx $0.15 - $0.25.
    Spreads above $0.40 indicate broker liquidity drain or news widening.
    """
    if spread <= 0:
        return True, "Spread is nominal (<= 0 or unavailable)"
    if spread > max_allowed_spread:
        return False, f"⚠️ SPREAD EXPANDED: สเปรดทองคำถ่างเกินเกณฑ์ (${spread:.2f} > ${max_allowed_spread:.2f}) ห้ามตั้ง Limit ป้องกัน Slippage"
    return True, f"สเปรดปกติ (${spread:.2f} <= ${max_allowed_spread:.2f})"

def is_volatility_spike(current_bar_range: float, current_atr: float, spike_multiplier: float = 1.8) -> Tuple[bool, str]:
    """
    Check if the latest candle's range is abnormally large compared to the recent ATR,
    signaling an unexpected headline news shock or market flash crash.
    """
    if current_atr <= 0:
        return False, "ATR is not available"
    if current_bar_range >= (spike_multiplier * current_atr):
        return True, f"⚠️ VOLATILITY SPIKE: แท่งเทียนกระชากแรงผิดปกติ (${current_bar_range:.2f} >= {spike_multiplier}x ATR ${current_atr:.2f}) เสี่ยงมีดบิน"
    return False, "ความผันผวนอยู่ในกรอบปกติ"
