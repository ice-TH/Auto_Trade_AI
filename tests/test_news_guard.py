from datetime import datetime, timezone
from src.risk.news_guard import (
    is_news_blackout,
    is_rollover_blackout,
    is_spread_acceptable,
    is_volatility_spike,
    to_bangkok,
    to_eastern,
)


def test_to_bangkok_and_eastern_dst():
    # Summer EDT (UTC-4): July 15, 2026 12:30 UTC -> 08:30 EDT / 19:30 BKK
    summer_utc = datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc)
    assert to_bangkok(summer_utc).hour == 19
    assert to_eastern(summer_utc).hour == 8

    # Winter EST (UTC-5): Nov 23, 2026 13:30 UTC -> 08:30 EST / 20:30 BKK
    winter_utc = datetime(2026, 11, 23, 13, 30, tzinfo=timezone.utc)
    assert to_bangkok(winter_utc).hour == 20
    assert to_eastern(winter_utc).hour == 8


def test_news_blackout_cpi_window_summer_and_winter():
    # Summer CPI at 08:30 EDT = 12:30 UTC (19:30 BKK)
    summer_cpi = datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc)
    in_summer, reason_s = is_news_blackout(summer_cpi)
    assert in_summer is True
    assert "NEWS BLACKOUT" in reason_s

    # Winter CPI at 08:30 EST = 13:30 UTC (20:30 BKK)
    winter_cpi = datetime(2026, 11, 23, 13, 30, tzinfo=timezone.utc)
    in_winter, reason_w = is_news_blackout(winter_cpi)
    assert in_winter is True
    assert "NEWS BLACKOUT" in reason_w

    # In Winter, 19:30 BKK (12:30 UTC = 07:30 EST) is 1 hour BEFORE CPI -> safe!
    winter_pre_news = datetime(2026, 11, 23, 12, 30, tzinfo=timezone.utc)
    in_pre, _ = is_news_blackout(winter_pre_news)
    assert in_pre is False


def test_news_blackout_fomc_window():
    # Winter FOMC at 14:15 EST = 19:15 UTC (02:15 BKK next day)
    fomc_time = datetime(2026, 11, 25, 19, 15, tzinfo=timezone.utc)
    in_news, reason = is_news_blackout(fomc_time)
    assert in_news is True
    assert "FOMC" in reason


def test_rollover_blackout_window():
    # 17:15 EST = 22:15 UTC (05:15 BKK) -> Daily Gold Rollover Break
    rollover_time = datetime(2026, 11, 24, 22, 15, tzinfo=timezone.utc)
    in_roll, reason = is_rollover_blackout(rollover_time)
    assert in_roll is True
    assert "ROLLOVER" in reason

    # Normal London session 09:00 UTC -> Not in rollover
    normal_time = datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc)
    assert is_rollover_blackout(normal_time)[0] is False


def test_news_blackout_quiet_hours_and_weekend():
    quiet_time = datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)
    in_news, reason = is_news_blackout(quiet_time)
    assert in_news is False
    assert "ปลอดภัย" in reason

    weekend_time = datetime(2026, 11, 28, 13, 30, tzinfo=timezone.utc)
    assert is_news_blackout(weekend_time)[0] is False


def test_spread_acceptable():
    assert is_spread_acceptable(0.20)[0] is True
    assert is_spread_acceptable(0.35)[0] is True

    ok, reason = is_spread_acceptable(0.65, max_allowed_spread=0.40)
    assert ok is False
    assert "SPREAD EXPANDED" in reason


def test_volatility_spike():
    assert is_volatility_spike(3.00, 2.00)[0] is False

    spike, reason = is_volatility_spike(5.00, 2.00, spike_multiplier=1.8)
    assert spike is True
    assert "VOLATILITY SPIKE" in reason
