from typing import List, Dict, Any, Optional
from src.data.base import Bar

def calculate_ema(bars: List[Bar], period: int) -> List[Dict[str, Any]]:
    """
    Calculate Exponential Moving Average (EMA) for given period.
    Returns list of dicts: [{'time': timestamp, 'value': rounded_ema}, ...]
    """
    if len(bars) < period:
        return []
        
    alpha = 2.0 / (period + 1.0)
    result: List[Dict[str, Any]] = []
    
    # Initialize with Simple Moving Average (SMA) of first 'period' bars
    initial_sum = sum(b.close for b in bars[:period])
    ema = initial_sum / float(period)
    
    # First recorded point at index period - 1
    result.append({
        "time": int(bars[period - 1].open_time.timestamp()),
        "value": round(ema, 2)
    })
    
    for i in range(period, len(bars)):
        c = bars[i].close
        ema = (c * alpha) + (ema * (1.0 - alpha))
        result.append({
            "time": int(bars[i].open_time.timestamp()),
            "value": round(ema, 2)
        })
        
    return result

def calculate_atr(bars: List[Bar], period: int = 14) -> List[Dict[str, Any]]:
    """
    Calculate Average True Range (ATR) using Wilder's smoothing.
    """
    if len(bars) < period + 1:
        return []
        
    tr_list: List[float] = []
    # TR calculation
    for i in range(1, len(bars)):
        h = bars[i].high
        l = bars[i].low
        c_prev = bars[i - 1].close
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        tr_list.append(tr)
        
    if len(tr_list) < period:
        return []
        
    # Initial ATR is simple average of first period TRs
    atr = sum(tr_list[:period]) / float(period)
    result: List[Dict[str, Any]] = []
    
    result.append({
        "time": int(bars[period].open_time.timestamp()),
        "value": round(atr, 2)
    })
    
    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / float(period)
        result.append({
            "time": int(bars[i + 1].open_time.timestamp()),
            "value": round(atr, 2)
        })
        
    return result

def calculate_sma(bars: List[Bar], period: int = 50) -> List[Dict[str, Any]]:
    """
    Calculate Simple Moving Average (SMA) for given period.
    Returns list of dicts: [{'time': timestamp, 'value': rounded_sma}, ...]
    """
    if len(bars) < period:
        return []
        
    result: List[Dict[str, Any]] = []
    current_sum = sum(b.close for b in bars[:period])
    result.append({
        "time": int(bars[period - 1].open_time.timestamp()),
        "value": round(current_sum / float(period), 2)
    })
    
    for i in range(period, len(bars)):
        current_sum += bars[i].close - bars[i - period].close
        result.append({
            "time": int(bars[i].open_time.timestamp()),
            "value": round(current_sum / float(period), 2)
        })
        
    return result

def calculate_volume_ma(bars: List[Bar], period: int = 20) -> List[Dict[str, Any]]:
    """Calculate Simple Moving Average of Volume."""
    if len(bars) < period:
        return []
        
    result: List[Dict[str, Any]] = []
    running_vol = sum(b.volume for b in bars[:period])
    result.append({
        "time": int(bars[period - 1].open_time.timestamp()),
        "value": round(running_vol / float(period), 0)
    })
    
    for i in range(period, len(bars)):
        running_vol += bars[i].volume - bars[i - period].volume
        result.append({
            "time": int(bars[i].open_time.timestamp()),
            "value": round(running_vol / float(period), 0)
        })
        
    return result
