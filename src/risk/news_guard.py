from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import json
import logging
import time as time_mod

from config.settings import BASE_DIR

logger = logging.getLogger(__name__)

TZ_UTC = timezone.utc
TZ_BANGKOK = ZoneInfo("Asia/Bangkok")
TZ_EASTERN = ZoneInfo("America/New_York")

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CALENDAR_CACHE_PATH = BASE_DIR / "memory" / "news_calendar_cache.json"
CALENDAR_CACHE_TTL_SECONDS = 7200  # 2 hours

IMPACT_LABELS = {
    "High": "กล่องแดง 🔴",
    "Medium": "กล่องส้ม 🟠",
    "Low": "กล่องเหลือง 🟡",
    "Holiday": "วันหยุดตลาด ⚪",
}

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


def _parse_event_datetime(date_str: str) -> Optional[datetime]:
    """Parse ISO-8601 event timestamp from ForexFactory JSON into UTC datetime."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_UTC)
        return dt.astimezone(TZ_UTC)
    except ValueError:
        return None


def fetch_economic_calendar(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Fetch weekly economic calendar from ForexFactory JSON feed with local file cache (2h TTL).
    Returns cached/stale data or [] if network is unavailable.
    """
    if not force_refresh and CALENDAR_CACHE_PATH.exists():
        try:
            age_sec = time_mod.time() - CALENDAR_CACHE_PATH.stat().st_mtime
            if age_sec < CALENDAR_CACHE_TTL_SECONDS:
                with open(CALENDAR_CACHE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            logger.debug(f"Failed to read fresh news calendar cache: {e}")

    try:
        req = Request(FF_CALENDAR_URL, headers={"User-Agent": "Mozilla/5.0 (AutoTrade-NewsGuard)"})
        with urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        if isinstance(data, list):
            CALENDAR_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CALENDAR_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return data
    except Exception as e:
        logger.warning(f"ForexFactory calendar fetch failed, checking stale cache / fallback: {e}")

    if CALENDAR_CACHE_PATH.exists():
        try:
            with open(CALENDAR_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass

    return []


def _calendar_covers_date(events: List[Dict[str, Any]], dt_utc: datetime) -> bool:
    """Return True if the fetched calendar events cover the calendar week of dt_utc."""
    parsed_dates = [d for ev in events if (d := _parse_event_datetime(str(ev.get("date", "")))) is not None]
    if not parsed_dates:
        return False
    min_dt = min(parsed_dates) - timedelta(days=1)
    max_dt = max(parsed_dates) + timedelta(days=1)
    return min_dt <= dt_utc <= max_dt


def get_news_impact_summary(
    dt: Optional[datetime] = None,
    currencies: Tuple[str, ...] = ("USD",),
) -> Dict[str, Any]:
    """
    Return today's economic calendar events for the given currencies with Red/Orange/Yellow box labels.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    dt_bkk = to_bangkok(dt)
    target_date_bkk = dt_bkk.date()

    events = fetch_economic_calendar()
    matched: List[Dict[str, Any]] = []

    for ev in events:
        country = str(ev.get("country", "")).upper()
        if currencies and country not in currencies:
            continue
        ev_utc = _parse_event_datetime(str(ev.get("date", "")))
        if ev_utc is None:
            continue
        ev_bkk = to_bangkok(ev_utc)
        if ev_bkk.date() != target_date_bkk:
            continue
        impact = str(ev.get("impact", "Low"))
        matched.append({
            "title": ev.get("title", "Unknown"),
            "currency": country,
            "impact": impact,
            "box_label": IMPACT_LABELS.get(impact, impact),
            "time_bkk": ev_bkk.strftime("%H:%M"),
            "forecast": ev.get("forecast", ""),
            "previous": ev.get("previous", ""),
        })

    matched.sort(key=lambda x: x["time_bkk"])
    return {
        "date_bkk": target_date_bkk.isoformat(),
        "source": "ForexFactory Live" if events else "Static Fallback",
        "events": matched,
    }


def is_news_blackout(
    dt: Optional[datetime] = None,
    use_live_calendar: bool = True,
    before_minutes: int = 30,
    after_minutes: int = 45,
) -> Tuple[bool, str]:
    """
    Check if the given time falls inside a high-impact news blackout window.
    Uses live ForexFactory calendar (Red/High USD events within [-30m, +45m]) when available
    for the current week, and falls back to DST-aware static US macro windows otherwise.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    dt_utc = dt.replace(tzinfo=TZ_UTC) if dt.tzinfo is None else dt.astimezone(TZ_UTC)
    dt_et = to_eastern(dt_utc)
    dt_bkk = to_bangkok(dt_utc)

    # US macro releases occur Monday (0) through Friday (4) in New York time
    if dt_et.weekday() >= 5:
        return False, "Weekend: Regular market closed"

    if use_live_calendar:
        events = fetch_economic_calendar()
        if events and _calendar_covers_date(events, dt_utc):
            for ev in events:
                if str(ev.get("country", "")).upper() != "USD":
                    continue
                if str(ev.get("impact", "")) != "High":
                    continue
                ev_utc = _parse_event_datetime(str(ev.get("date", "")))
                if ev_utc is None:
                    continue
                win_start = ev_utc - timedelta(minutes=before_minutes)
                win_end = ev_utc + timedelta(minutes=after_minutes)
                if win_start <= dt_utc <= win_end:
                    ev_bkk = to_bangkok(ev_utc)
                    title = ev.get("title", "High Impact News")
                    return True, (
                        f"⚠️ NEWS BLACKOUT ({dt_bkk.strftime('%H:%M')} BKK / {dt_et.strftime('%H:%M')} ET): "
                        f"กล่องแดง 🔴 {title} (USD เวลา {ev_bkk.strftime('%H:%M')} BKK) ห้ามวางคำสั่งใหม่ [XAU-RULE-17]"
                    )

            return False, (
                f"สภาวะเวลาปกติ: ปลอดภัย ไม่มีข่าวกล่องแดง 🔴 USD ในช่วง -{before_minutes}/+{after_minutes} นาที (Live Calendar)"
            )

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
