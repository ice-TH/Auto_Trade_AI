from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo
from src.risk.news_guard import (
    is_news_blackout,
    is_spread_acceptable,
    is_volatility_spike,
    to_bangkok,
    TZ_BANGKOK
)

def test_to_bangkok():
    utc_dt = datetime(2026, 11, 23, 12, 30, tzinfo=timezone.utc)
    bkk_dt = to_bangkok(utc_dt)
    assert bkk_dt.hour == 19
    assert bkk_dt.minute == 30

def test_news_blackout_cpi_window():
    # 19:30 BKK (12:30 UTC) on a Monday -> Should trigger News Blackout
    news_time = datetime(2026, 11, 23, 12, 30, tzinfo=timezone.utc)
    in_news, reason = is_news_blackout(news_time)
    assert in_news is True
    assert "NEWS BLACKOUT" in reason

def test_news_blackout_fomc_window():
    # 01:15 BKK (18:15 UTC previous day) on Wednesday -> Should trigger FOMC Blackout
    fomc_time = datetime(2026, 11, 25, 18, 15, tzinfo=timezone.utc)
    in_news, reason = is_news_blackout(fomc_time)
    assert in_news is True
    assert "FOMC" in reason

def test_news_blackout_quiet_hours():
    # 14:00 BKK (07:00 UTC) -> Regular London morning, safe from major US news
    quiet_time = datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)
    in_news, reason = is_news_blackout(quiet_time)
    assert in_news is False
    assert "ปลอดภัย" in reason

def test_news_blackout_weekend():
    # Saturday 19:30 BKK -> Market closed, no active blackout execution
    weekend_time = datetime(2026, 11, 28, 12, 30, tzinfo=timezone.utc)
    in_news, reason = is_news_blackout(weekend_time)
    assert in_news is False

def test_spread_acceptable():
    assert is_spread_acceptable(0.20)[0] is True
    assert is_spread_acceptable(0.35)[0] is True
    
    # Spread widened to $0.65 -> rejected
    ok, reason = is_spread_acceptable(0.65, max_allowed_spread=0.40)
    assert ok is False
    assert "SPREAD EXPANDED" in reason

def test_volatility_spike():
    # Bar range $3.00, ATR $2.00 -> 1.5x (Normal)
    assert is_volatility_spike(3.00, 2.00)[0] is False
    
    # Bar range $5.00, ATR $2.00 -> 2.5x (Spike!)
    spike, reason = is_volatility_spike(5.00, 2.00, spike_multiplier=1.8)
    assert spike is True
    assert "VOLATILITY SPIKE" in reason
