from datetime import datetime, timezone
from src.risk.earnings_guard import is_near_earnings, clean_symbol

def test_clean_symbol():
    assert clean_symbol("AAPL.m") == "AAPL"
    assert clean_symbol("NVDA") == "NVDA"
    assert clean_symbol("GOOGLm") == "GOOGL"

def test_is_near_earnings_detected():
    # Apple earnings on 2026-01-29. Check from 2026-01-28 (1 day before)
    dt_near = datetime(2026, 1, 28, 14, 0, tzinfo=timezone.utc)
    near, reason = is_near_earnings("AAPL", current_dt=dt_near, buffer_days=2)
    assert near is True
    assert "EARNINGS BLACKOUT" in reason

def test_is_near_earnings_safe():
    # Check Apple on 2026-03-15 (Peaceful period between Q1 and Q2)
    dt_safe = datetime(2026, 3, 15, 14, 0, tzinfo=timezone.utc)
    near, reason = is_near_earnings("AAPL", current_dt=dt_safe, buffer_days=2)
    assert near is False
    assert "ปลอดภัย" in reason
