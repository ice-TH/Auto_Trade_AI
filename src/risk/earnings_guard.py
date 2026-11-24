from datetime import datetime, date, timezone, timedelta
from typing import Tuple, Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

# Sample upcoming earnings dates for Magnificent 7 (simulated & updated schedule)
# Dates formatted as YYYY-MM-DD
EARNINGS_SCHEDULE: Dict[str, List[str]] = {
    "AAPL": ["2026-01-29", "2026-04-30", "2026-07-30", "2026-10-29"],
    "MSFT": ["2026-01-27", "2026-04-28", "2026-07-28", "2026-10-27"],
    "NVDA": ["2026-02-25", "2026-05-27", "2026-08-26", "2026-11-18"],
    "AMZN": ["2026-02-05", "2026-04-30", "2026-07-30", "2026-10-29"],
    "GOOGL": ["2026-02-03", "2026-04-28", "2026-07-28", "2026-10-27"],
    "META": ["2026-02-04", "2026-04-29", "2026-07-29", "2026-10-28"],
    "TSLA": ["2026-01-28", "2026-04-22", "2026-07-22", "2026-10-21"],
}

def clean_symbol(symbol: str) -> str:
    """Normalize symbol by stripping broker prefixes/suffixes (e.g., AAPL.m -> AAPL)."""
    s = symbol.upper()
    for clean in ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]:
        if clean in s:
            return clean
    return s.replace(".M", "").replace("M", "").replace(".", "")

def is_near_earnings(symbol: str, current_dt: Optional[datetime] = None, buffer_days: int = 2) -> Tuple[bool, str]:
    """
    Check if a stock is within the buffer window (e.g. 48 hours / 2 days) of its quarterly earnings release.
    Holding or entering before earnings carries catastrophic overnight gap risk (10-20%).
    """
    if current_dt is None:
        current_dt = datetime.now(timezone.utc)
        
    current_date = current_dt.date()
    stock_sym = clean_symbol(symbol)
    
    dates = EARNINGS_SCHEDULE.get(stock_sym, [])
    for d_str in dates:
        try:
            e_date = datetime.strptime(d_str, "%Y-%m-%d").date()
            diff = (e_date - current_date).days
            # If earnings is today or within the next buffer_days days, or occurred yesterday
            if -1 <= diff <= buffer_days:
                return True, (
                    f"⚠️ EARNINGS BLACKOUT: {stock_sym} มีกำหนดประกาศงบการเงิน ({d_str}) "
                    f"อยู่ในช่วงเสี่ยงสูง ({diff} วัน) ห้ามเปิดสถานะ Swing Trade ป้องกัน Gap ถล่ม [EQ-RULE-07]"
                )
        except ValueError:
            continue
            
    return False, f"ปลอดภัย: {stock_sym} ไม่อยู่ในช่วงประกาศงบการเงินในอีก {buffer_days} วัน"
