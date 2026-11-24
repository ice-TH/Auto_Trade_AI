from datetime import datetime, time, timezone
from typing import Tuple, Optional
from zoneinfo import ZoneInfo
import logging

logger = logging.getLogger(__name__)

TZ_UTC = timezone.utc
TZ_BANGKOK = ZoneInfo("Asia/Bangkok")
TZ_EASTERN = ZoneInfo("America/New_York")

# DST-Aware High-Impact US Macro News Release Windows (anchored to America/New_York ET)
# Automatically shifts between Summer (EDT, UTC-4) and Winter (EST, UTC-5) without manual edits:
# 1. 08:15 - 09:45 ET (19:15-20:45 BKK Summer / 20:15-21:45 BKK Winter): CPI, PPI, NFP, GDP, Retail Sales, Jobless Claims (08:30 ET)
# 2. 09:45 - 11:15 ET (20:45-22:15 BKK Summer / 21:45-23:15 BKK Winter): ISM PMI, JOLTS, Consumer Confidence (10:00 ET)
# 3. 13:45 - 15:30 ET (00:45-02:30 BKK Summer / 01:45-03:30 BKK Winter): FOMC Rate Decision & Fed Chair Press Conference (14:00-14:30 ET)
HIGH_IMPACT_NEWS_WINDOWS_ET = [
    (time(8, 15), time(9, 45), "US Morning Data / CPI / NFP / PPI (08:30 ET)"),
    (time(9, 45), time(11, 15), "ISM / PMI / Consumer Confidence (10:00 ET)"),
    (time(13, 45), time(15, 30), "FOMC Rate Decision / Fed Statements (14:00 ET)"),
]

# Gold Daily Rollover / Illiquid Close Window in New York Time:
# CME/CFD Gold daily break occurs 17:00 - 18:00 ET. Spreads widen sharply 30m before and 15m after.
GOLD_ROLLOVER_WINDOW_ET = (time(16, 30), time(18, 15))


def to_bangkok(dt: datetime) -> datetime:
    """Convert any aware or naive datetime to Asia/Bangkok time (UTC+7)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_UTC)
    return dt.astimezone(TZ_BANGKOK)


def to_eastern(dt: datetime) -> datetime:
    """Convert any aware or naive datetime to America/New_York time (EDT/EST)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_UTC)
    return dt.astimezone(TZ_EASTERN)


def is_rollover_blackout(dt: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    Check if current time falls inside the daily Gold rollover / session close maintenance window
    (16:30 - 18:15 ET -> 03:30 - 05:15 BKK in EDT / 04:30 - 06:15 BKK in EST).
    Prevents overnight spread traps and new entries right before market close [XAU-RULE-09].
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    dt_et = to_eastern(dt)
    dt_bkk = to_bangkok(dt)

    # Weekend check in NY time (Friday >= 16:30 ET through Sunday < 18:15 ET)
    wd = dt_et.weekday()  # Mon=0 ... Fri=4, Sat=5, Sun=6
    curr_t = dt_et.time()
    start_t, end_t = GOLD_ROLLOVER_WINDOW_ET

    if wd == 5 or (wd == 4 and curr_t >= start_t) or (wd == 6 and curr_t <= end_t):
        return True, f"⚠️ MARKET CLOSED / WEEKEND ROLLOVER ({dt_bkk.strftime('%H:%M')} BKK): ตลาดทองคำปิดทำการสุดสัปดาห์/ช่วงเปิดตลาดเช้าวันจันทร์"

    if start_t <= curr_t <= end_t:
        return True, (
            f"⚠️ ROLLOVER BLACKOUT ({dt_bkk.strftime('%H:%M')} BKK / {dt_et.strftime('%H:%M')} ET): "
            f"ช่วงพักเซสชัน/ข้ามวันของทองคำ สเปรดถ่างสูง งดเปิดหรือค้างคำสั่ง Limit [XAU-RULE-09]"
        )

    return False, "ไม่อยู่ในช่วงพักตลาด Rollover"


def is_news_blackout(dt: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    Check if the given time falls inside a DST-aware high-impact US macro news blackout window.
    During news blackout windows, all Pending Orders must be cancelled and no new limits placed.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    dt_et = to_eastern(dt)
    dt_bkk = to_bangkok(dt)

    # US macro releases occur Monday (0) through Friday (4) in New York time
    if dt_et.weekday() >= 5:
        return False, "Weekend: Regular market closed"

    current_et = dt_et.time()

    for start_t, end_t, desc in HIGH_IMPACT_NEWS_WINDOWS_ET:
        if start_t <= end_t:
            if start_t <= current_et <= end_t:
                return True, (
                    f"⚠️ NEWS BLACKOUT ({dt_bkk.strftime('%H:%M')} BKK / {dt_et.strftime('%H:%M')} ET): "
                    f"อยู่ในช่วงข่าวแรงสหรัฐฯ ({desc}) ห้ามวางคำสั่งใหม่ [XAU-RULE-17]"
                )
        else:
            if current_et >= start_t or current_et <= end_t:
                return True, (
                    f"⚠️ NEWS BLACKOUT ({dt_bkk.strftime('%H:%M')} BKK / {dt_et.strftime('%H:%M')} ET): "
                    f"อยู่ในช่วงข่าวแรงสหรัฐฯ ({desc}) ห้ามวางคำสั่งใหม่ [XAU-RULE-17]"
                )

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
        return False, f"⚠️ SPREAD EXPANDED: สเปรดทองคำถ่างเกินเกณฑ์ (${spread:.2f} > ${max_allowed_spread:.2f}) ห้ามตั้งคำสั่ง ป้องกัน Slippage"
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
