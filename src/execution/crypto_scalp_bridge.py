"""
Crypto Scalping Bridge CLI - Dedicated for fast, short-term BTC scalping (M1, M5, M15).
Connects directly to Exness MT5 (e.g. BTCUSDm) for Antigravity AI high-frequency reasoning & execution.
"""
import sys
import os
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

from src.execution.mt5_client import mt5_client

CRYPTO_SYMBOL = "BTCUSDm"

def ensure_symbol_active(symbol: str = CRYPTO_SYMBOL) -> bool:
    if not MT5_AVAILABLE:
        return False
    if not mt5_client.is_connected:
        mt5_client.connect()
    
    # Check symbol availability
    info = mt5.symbol_info(symbol)
    if info is None:
        # Fallback to BTCUSD if BTCUSDm not found
        if mt5.symbol_info("BTCUSD"):
            symbol = "BTCUSD"
            info = mt5.symbol_info(symbol)
    
    if info and not info.visible:
        mt5.symbol_select(symbol, True)
    return info is not None

def calculate_ema(prices: List[float], period: int) -> List[float]:
    if len(prices) < period:
        return []
    multiplier = 2.0 / (period + 1)
    ema = [sum(prices[:period]) / period]
    for price in prices[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema

def calculate_rsi(prices: List[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)

def scan_btc_scalp(symbol: str = CRYPTO_SYMBOL) -> Dict[str, Any]:
    """
    Fetch high-speed M1, M5, M15 bars, calculate momentum, RSI, EMA 9/21,
    and generate an aggressive fast scalp recommendation.
    """
    if not ensure_symbol_active(symbol):
        return {"error": f"Failed to activate symbol {symbol} in MT5"}

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return {"error": f"Cannot get tick data for {symbol}"}

    bid = tick.bid
    ask = tick.ask
    spread = round(ask - bid, 2)

    # 1. Fetch M1 (Fast Trigger) - Fetch 100 bars for MA(50) calculation
    rates_m1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 100)
    # 2. Fetch M5 (Short-term Trend)
    rates_m5 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 100)
    # 3. Fetch M15 (Structure)
    rates_m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 50)

    if rates_m1 is None or len(rates_m1) < 25:
        return {"error": "Insufficient M1 bars for scalping"}

    closes_m1 = [float(r["close"]) for r in rates_m1]
    closes_m5 = [float(r["close"]) for r in rates_m5] if rates_m5 is not None else []

    # Indicators on M1: EMA(15) and MA(50)
    ema15_m1 = calculate_ema(closes_m1, 15)
    ma50_val = sum(closes_m1[-50:]) / 50.0 if len(closes_m1) >= 50 else (sum(closes_m1) / len(closes_m1))
    rsi_m1 = calculate_rsi(closes_m1, 14)
    rsi_m5 = calculate_rsi(closes_m5, 14) if closes_m5 else 50.0

    curr_price = closes_m1[-1]
    fast_trend = "BULLISH_SURGE" if ema15_m1 and ema15_m1[-1] > ma50_val else "BEARISH_DUMP"

    # Calculate M1 ATR for dynamic volatility buffer
    highs_m1 = [float(r["high"]) for r in rates_m1]
    lows_m1 = [float(r["low"]) for r in rates_m1]
    tr_list = [
        max(highs_m1[i] - lows_m1[i], abs(highs_m1[i] - closes_m1[i - 1]), abs(lows_m1[i] - closes_m1[i - 1]))
        for i in range(1, len(rates_m1))
    ]
    atr_m1 = sum(tr_list[-14:]) / 14.0 if len(tr_list) >= 14 else 50.0

    # Dynamic Spread & Volatility Buffers
    # SL Moat Buffer: Protects against spread widen and wick sweeps
    # Note: Ensure buffers adapt strictly to symbol price scale (BTC vs Gold vs Others)
    is_gold = "XAU" in symbol.upper()
    if is_gold:
        sl_moat_buffer = round(max(atr_m1 * 1.0, spread * 2.0, 3.5), 2)
        tp_front_buffer = round(max(atr_m1 * 0.5, spread * 1.5, 1.5), 2)
        tp_reach_target = round(max(atr_m1 * 2.5, sl_moat_buffer * 1.5, 8.0), 2)
    else:
        sl_moat_buffer = round(max(atr_m1 * 0.75, spread * 2.0, 80.0), 2)
        tp_front_buffer = round(max(atr_m1 * 0.35, spread * 1.5, 40.0), 2)
        tp_reach_target = round(max(atr_m1 * 2.0, sl_moat_buffer * 1.25, 180.0), 2)

    # Fast Scalp Setup Logic with Dynamic Buffer
    signal = "NEUTRAL"

    if fast_trend == "BULLISH_SURGE" and rsi_m1 < 68:
        signal = "SCALP_BUY"
        entry = ask
        # SL tucked safely below entry + buffer + spread
        sl = round(entry - sl_moat_buffer - spread, 2)
        # TP front-runs the target by pulling back tp_front_buffer
        tp = round(entry + tp_reach_target - tp_front_buffer, 2)
    elif fast_trend == "BEARISH_DUMP" and rsi_m1 > 32:
        signal = "SCALP_SELL"
        entry = bid
        # SL tucked safely above entry + buffer + spread
        sl = round(entry + sl_moat_buffer + spread, 2)
        # TP front-runs the target downward
        tp = round(entry - tp_reach_target + tp_front_buffer, 2)
    else:
        entry = curr_price
        sl = 0.0
        tp = 0.0

    return {
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market": {
            "bid": bid,
            "ask": ask,
            "spread_usd": spread,
            "current_price": curr_price
        },
        "scalp_indicators": {
            "m1_rsi": rsi_m1,
            "m5_rsi": rsi_m5,
            "m1_ema15": round(ema15_m1[-1], 2) if ema15_m1 else None,
            "m1_ma50": round(ma50_val, 2) if ma50_val else None,
            "momentum": fast_trend
        },
        "scalp_plan": {
            "signal": signal,
            "recommended_volume": 0.01,
            "entry_target": entry,
            "stop_loss": sl,
            "take_profit": tp,
            "risk_usd": round(abs(entry - sl) * 0.01, 2) if sl > 0 else 0.0,
            "target_reward_usd": round(abs(tp - entry) * 0.01, 2) if tp > 0 else 0.0,
            "sl_moat_buffer": sl_moat_buffer,
            "tp_front_buffer": tp_front_buffer,
            "spread_usd": spread
        }
    }

def execute_crypto_scalp(direction: str, volume: float = 0.01, sl: float = 0.0, tp: float = 0.0, symbol: str = CRYPTO_SYMBOL) -> Dict[str, Any]:
    """Execute aggressive crypto scalp order with tight stop loss."""
    ensure_symbol_active(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return {"success": False, "error": f"Cannot get tick price for {symbol}"}

    price = tick.ask if direction.upper() == "BUY" else tick.bid
    # Default auto SL/TP if not provided
    is_gold = "XAU" in symbol.upper()
    if sl <= 0:
        default_sl_dist = 4.0 if is_gold else 150.0
        sl = round(price - default_sl_dist if direction.upper() == "BUY" else price + default_sl_dist, 2)
    if tp <= 0:
        default_tp_dist = 8.0 if is_gold else 300.0
        tp = round(price + default_tp_dist if direction.upper() == "BUY" else price - default_tp_dist, 2)

    return mt5_client.send_order(
        symbol=symbol,
        direction=direction.upper(),
        volume=volume,
        sl_price=sl,
        tp_price=tp,
        comment="Antigravity Gold Scalp" if is_gold else "Antigravity BTC Scalp"
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Antigravity Crypto Scalping CLI")
    parser.add_argument("action", choices=["scan", "buy", "sell", "positions", "close-all"])
    parser.add_argument("--symbol", type=str, default=CRYPTO_SYMBOL)
    parser.add_argument("--volume", type=float, default=0.01)
    parser.add_argument("--sl", type=float, default=0.0)
    parser.add_argument("--tp", type=float, default=0.0)

    args = parser.parse_args()

    if args.action == "scan":
        res = scan_btc_scalp(args.symbol)
        print(json.dumps(res, indent=2))
    elif args.action in ["buy", "sell"]:
        direction = "BUY" if args.action == "buy" else "SELL"
        res = execute_crypto_scalp(direction, args.volume, args.sl, args.tp, args.symbol)
        print(json.dumps(res, indent=2))
    elif args.action == "positions":
        ensure_symbol_active(args.symbol)
        all_pos = mt5_client.get_open_positions() if mt5_client.is_connected else []
        filtered_pos = [p for p in all_pos if args.symbol.upper() in p.get("symbol", "").upper()] if args.symbol else all_pos
        print(json.dumps({"open_positions": filtered_pos, "all_positions": all_pos}, indent=2))
    elif args.action == "close-all":
        res = mt5_client.emergency_close_all()
        print(json.dumps(res, indent=2))
