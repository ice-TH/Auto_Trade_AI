from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from src.data.calendar_guard import (
    TZ_UTC, TZ_EASTERN, TZ_BANGKOK, to_eastern, to_bangkok, get_market_session, SessionType
)

def test_timezone_conversions():
    dt_utc = datetime(2026, 6, 15, 13, 30, tzinfo=TZ_UTC) # 13:30 UTC in June (EDT = UTC-4)
    dt_et = to_eastern(dt_utc)
    assert dt_et.hour == 9
    assert dt_et.minute == 30
    
    dt_bkk = to_bangkok(dt_utc) # Bangkok = UTC+7 -> 20:30
    assert dt_bkk.hour == 20
    assert dt_bkk.minute == 30

def test_market_session_rth():
    # Wednesday 10:00 AM Eastern Time = Regular Trading Hours
    dt_utc = datetime(2026, 6, 17, 14, 0, tzinfo=TZ_UTC) # 14:00 UTC = 10:00 ET
    session = get_market_session(dt_utc)
    assert session == SessionType.REGULAR

def test_market_session_weekend():
    # Saturday 14:00 UTC = Closed
    dt_utc = datetime(2026, 6, 20, 14, 0, tzinfo=TZ_UTC)
    session = get_market_session(dt_utc)
    assert session == SessionType.CLOSED
