from datetime import datetime, time, date, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Tuple
from src.data.base import SessionType, TimeFrame

TZ_UTC = timezone.utc
TZ_EASTERN = ZoneInfo("America/New_York")
TZ_BANGKOK = ZoneInfo("Asia/Bangkok")

# US Regular Market Hours in Eastern Time
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)
PRE_MARKET_OPEN = time(4, 0)
POST_MARKET_CLOSE = time(20, 0)

US_FIXED_HOLIDAYS = {
    (1, 1): "New Year's Day",
    (6, 19): "Juneteenth",
    (7, 4): "Independence Day",
    (12, 25): "Christmas Day",
}

def to_eastern(dt: datetime) -> datetime:
    """Convert any aware or naive UTC datetime to US Eastern time."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_UTC)
    return dt.astimezone(TZ_EASTERN)

def to_bangkok(dt: datetime) -> datetime:
    """Convert any datetime to Asia/Bangkok time (UTC+7)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_UTC)
    return dt.astimezone(TZ_BANGKOK)

def is_weekend(dt_eastern: datetime) -> bool:
    """Return True if Eastern time is Saturday (5) or Sunday (6)."""
    return dt_eastern.weekday() >= 5

def get_market_session(dt: datetime) -> SessionType:
    """Determine US stock market session from given datetime (handled in Eastern Time)."""
    dt_et = to_eastern(dt)
    if is_weekend(dt_et):
        return SessionType.CLOSED

    # Check holiday
    if (dt_et.month, dt_et.day) in US_FIXED_HOLIDAYS:
        return SessionType.CLOSED

    t = dt_et.time()
    if RTH_OPEN <= t < RTH_CLOSE:
        return SessionType.REGULAR
    elif PRE_MARKET_OPEN <= t < RTH_OPEN:
        return SessionType.PRE_MARKET
    elif RTH_CLOSE <= t < POST_MARKET_CLOSE:
        return SessionType.POST_MARKET
    else:
        return SessionType.CLOSED

def get_bar_close_time(open_time_utc: datetime, timeframe: TimeFrame) -> datetime:
    """Calculate the expected close time for a bar based on timeframe."""
    if timeframe == TimeFrame.M15:
        return open_time_utc + timedelta(minutes=15)
    elif timeframe == TimeFrame.DAY:
        # A day bar closes at market close (16:00 ET) on that trade day
        open_et = to_eastern(open_time_utc)
        close_et = open_et.replace(hour=16, minute=0, second=0, microsecond=0)
        return close_et.astimezone(TZ_UTC)
    elif timeframe == TimeFrame.WEEK:
        # A week bar closes on Friday at market close (16:00 ET)
        open_et = to_eastern(open_time_utc)
        days_to_friday = (4 - open_et.weekday()) % 7
        friday_et = open_et + timedelta(days=days_to_friday)
        close_et = friday_et.replace(hour=16, minute=0, second=0, microsecond=0)
        return close_et.astimezone(TZ_UTC)
    return open_time_utc + timedelta(minutes=15)

def is_bar_closed(open_time_utc: datetime, timeframe: TimeFrame, current_utc: datetime) -> bool:
    """Check if the bar is strictly closed and confirmed. Prevents look-ahead bias."""
    close_time = get_bar_close_time(open_time_utc, timeframe)
    return current_utc >= close_time
