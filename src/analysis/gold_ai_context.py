"""
Gold AI Trader Context & Base-Anchored Chart Renderer (Mode 2 - Standalone).
Provides raw M5/M15/H1 candlestick telemetry, zone/Fibonacci structure, portfolio state,
and TradingView-style dual-panel charts (anchored strictly at Base creation time)
without modifying any Mode 1 (Rule-based EA) modules.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

from config.settings import settings
from src.data.base import Bar, TimeFrame
from src.data.mt5_adapter import MT5DataAdapter
from src.execution.mt5_client import MT5Client, mt5_client
from src.analysis.gold_strategy import (
    MIN_GOLD_SL_USD,
    MAX_GOLD_SL_USD,
    MIN_GOLD_RR_RATIO,
    detect_demand_supply_zones,
    scan_gold_setup,
)
from src.risk.news_guard import (
    TZ_BANGKOK,
    to_bangkok,
    is_news_blackout,
    is_rollover_blackout,
    is_spread_acceptable,
    is_volatility_spike,
)

logger = logging.getLogger("gold_ai_context")


def summarize_candles(bars: List[Bar], atr: float, limit: int = 15) -> List[Dict[str, Any]]:
    """Convert raw Bar objects into compact, exact Price Action metrics for AI reasoning."""
    if not bars:
        return []
    safe_atr = atr if (atr and atr > 0) else 1.0
    out: List[Dict[str, Any]] = []
    for b in bars[-limit:]:
        rng = max(b.high - b.low, 0.0)
        body = abs(b.close - b.open)
        upper_wick = b.high - max(b.open, b.close)
        lower_wick = min(b.open, b.close) - b.low
        out.append({
            "bkk_time": to_bangkok(b.open_time).strftime("%Y-%m-%d %H:%M"),
            "open": round(b.open, 2),
            "high": round(b.high, 2),
            "low": round(b.low, 2),
            "close": round(b.close, 2),
            "dir": "BULL" if b.close >= b.open else "BEAR",
            "body_usd": round(body, 2),
            "range_usd": round(rng, 2),
            "upper_wick_pct": round((upper_wick / rng) * 100.0, 1) if rng > 0 else 0.0,
            "lower_wick_pct": round((lower_wick / rng) * 100.0, 1) if rng > 0 else 0.0,
            "range_x_atr": round(rng / safe_atr, 2),
            "confirmed": bool(b.is_confirmed),
        })
    return out


def _get_recent_closed_trades(limit: int = 5) -> List[Dict[str, Any]]:
    """Fetch last N closed Gold trades from SQLite trade_history for AI self-awareness."""
    try:
        from src.storage.database import SessionLocal
        from src.storage.models import TradeHistoryModel
        db = SessionLocal()
        try:
            rows = (
                db.query(TradeHistoryModel)
                .filter(TradeHistoryModel.symbol.ilike("%XAU%"))
                .order_by(TradeHistoryModel.close_time.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "ticket": r.ticket,
                    "symbol": r.symbol,
                    "direction": r.direction,
                    "close_price": r.close_price,
                    "profit_usd": r.profit_usd,
                    "outcome": r.outcome,
                    "exit_reason": r.exit_reason,
                    "close_time": r.close_time.isoformat() if r.close_time else None,
                }
                for r in rows
            ]
        finally:
            db.close()
    except Exception as exc:
        logger.debug(f"Could not read recent trade history: {exc}")
        return []


def _parse_iso_utc(ts_str: Any) -> Optional[datetime]:
    if not ts_str:
        return None
    if isinstance(ts_str, datetime):
        return ts_str if ts_str.tzinfo else ts_str.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _calc_ema_series(closes: List[float], period: int) -> List[float]:
    if not closes:
        return []
    k = 2.0 / (period + 1.0)
    res = [closes[0]]
    for val in closes[1:]:
        res.append(val * k + res[-1] * (1.0 - k))
    return res


def _calc_sma_series(closes: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for i in range(len(closes)):
        if i + 1 < period:
            out.append(None)
        else:
            out.append(sum(closes[i + 1 - period : i + 1]) / float(period))
    return out


def _draw_candlestick_panel(
    ax: Any,
    bars: List[Bar],
    all_bars_for_ma: List[Bar],
    demands: List[Dict[str, Any]],
    supplies: List[Dict[str, Any]],
    fibo_buy: Dict[str, Any],
    fibo_sell: Dict[str, Any],
    current_price: float,
    panel_title: str,
    planned_trade: Optional[Dict[str, Any]] = None,
) -> None:
    """Render candlesticks + Base-origin-anchored Demand/Supply rectangles + Fibo + Entry/SL/TP."""
    ax.set_facecolor("#131722")
    if not bars:
        ax.text(0.5, 0.5, "No MT5 Bars Available", color="#94a3b8", ha="center", va="center", fontsize=12)
        ax.set_title(panel_title, color="#e2e8f0", fontsize=10.5, fontweight="bold")
        return

    n = len(bars)
    bar_times = [b.open_time if b.open_time.tzinfo else b.open_time.replace(tzinfo=timezone.utc) for b in bars]

    # 1. Draw candlesticks
    width = 0.62
    for i, b in enumerate(bars):
        is_bull = b.close >= b.open
        col = "#089981" if is_bull else "#f23645"
        ax.plot([i, i], [b.low, b.high], color=col, linewidth=1.1, zorder=3)
        body_low = min(b.open, b.close)
        body_h = max(abs(b.close - b.open), 0.03)
        ax.add_patch(
            patches.Rectangle(
                (i - width / 2.0, body_low),
                width,
                body_h,
                facecolor=col,
                edgecolor=col,
                linewidth=0.5,
                zorder=4,
            )
        )

    # 2. Moving Averages (EMA 15 & MA 50 computed over full history, sliced to visible window)
    full_closes = [b.close for b in all_bars_for_ma] if len(all_bars_for_ma) >= n else [b.close for b in bars]
    ema15 = _calc_ema_series(full_closes, 15)[-n:]
    sma50 = _calc_sma_series(full_closes, 50)[-n:]

    ax.plot(range(n), ema15, color="#f59e0b", linewidth=1.2, linestyle="--", label="EMA 15", alpha=0.9, zorder=5)
    valid_50 = [(idx, val) for idx, val in enumerate(sma50) if val is not None]
    if valid_50:
        x50, y50 = zip(*valid_50)
        ax.plot(x50, y50, color="#38bdf8", linewidth=1.4, label="MA 50", alpha=0.9, zorder=5)

    # 3. Draw Active Demand & Supply Zones anchored strictly at Base `created_time` (NO full-width axhspan!)
    def _find_anchor_index(created_time_raw: Any) -> int:
        dt = _parse_iso_utc(created_time_raw)
        if dt is None:
            return 0
        for idx, bt in enumerate(bar_times):
            if bt >= dt:
                return idx
        # If created_time is slightly newer than last bar open, anchor at last 2 bars
        return max(0, n - 2)

    right_ext = n + 3
    visible_low = min(b.low for b in bars)
    visible_high = max(b.high for b in bars)
    pad = max((visible_high - visible_low) * 0.18, 4.0)

    y_min = visible_low - pad * 0.5
    y_max = visible_high + pad * 0.5

    for z in (demands or [])[:3]:
        zl, zh = float(z["zone_low"]), float(z["zone_high"])
        if zh < y_min or zl > y_max:
            continue
        start_x = _find_anchor_index(z.get("created_time"))
        ax.add_patch(
            patches.Rectangle(
                (start_x, zl),
                right_ext - start_x,
                max(zh - zl, 0.10),
                linewidth=1.1,
                edgecolor="#00c076",
                facecolor="#00c076",
                alpha=0.18,
                clip_on=True,
                zorder=2,
            )
        )
        ymid = max(min((zl + zh) / 2.0, y_max - 1.0), y_min + 1.0)
        lbl = f"{z.get('pattern', 'DEM')} {z.get('timeframe', '')} [{zl:.1f}-{zh:.1f}]"
        ax.text(right_ext - 0.3, ymid, lbl, color="#34d399", fontsize=7.5, ha="right", va="center", fontweight="bold", clip_on=True, zorder=6)

    for z in (supplies or [])[:3]:
        zl, zh = float(z["zone_low"]), float(z["zone_high"])
        if zh < y_min or zl > y_max:
            continue
        start_x = _find_anchor_index(z.get("created_time"))
        ax.add_patch(
            patches.Rectangle(
                (start_x, zl),
                right_ext - start_x,
                max(zh - zl, 0.10),
                linewidth=1.1,
                edgecolor="#ef4444",
                facecolor="#ef4444",
                alpha=0.18,
                clip_on=True,
                zorder=2,
            )
        )
        ymid = max(min((zl + zh) / 2.0, y_max - 1.0), y_min + 1.0)
        lbl = f"{z.get('pattern', 'SUP')} {z.get('timeframe', '')} [{zl:.1f}-{zh:.1f}]"
        ax.text(right_ext - 0.3, ymid, lbl, color="#f87171", fontsize=7.5, ha="right", va="center", fontweight="bold", clip_on=True, zorder=6)

    # 4. Plot active Fibonacci 65% OTE if within reasonable chart range
    for fib_obj, tag in ((fibo_buy, "Buy OTE 65%"), (fibo_sell, "Sell OTE 65%")):
        f65 = fib_obj.get("fibo_650") if isinstance(fib_obj, dict) else None
        if f65 and (y_min <= float(f65) <= y_max):
            ax.axhline(float(f65), color="#fbbf24", linestyle=":", linewidth=1.0, alpha=0.75, zorder=3)
            ax.text(0.5, float(f65), f" {tag}: ${float(f65):.2f}", color="#fbbf24", fontsize=7.2, va="bottom", clip_on=True, zorder=6)

    # 5. Live Price & Optional Planned Trade Lines (Entry / SL / TP)
    if current_price > 0:
        ax.axhline(current_price, color="#e2e8f0", linestyle="-.", linewidth=0.9, alpha=0.7, zorder=5)

    if planned_trade:
        ep = float(planned_trade.get("entry") or 0.0)
        sl = float(planned_trade.get("sl") or 0.0)
        tp = float(planned_trade.get("tp") or 0.0)
        if ep > 0:
            ax.axhline(ep, color="#3b82f6", linestyle="-", linewidth=1.3, label=f"Entry ${ep:.2f}", zorder=6)
        if sl > 0:
            ax.axhline(sl, color="#ef4444", linestyle="--", linewidth=1.3, label=f"SL ${sl:.2f}", zorder=6)
        if tp > 0:
            ax.axhline(tp, color="#10b981", linestyle="--", linewidth=1.3, label=f"TP ${tp:.2f}", zorder=6)

    # X-axis BKK timestamps (avoid colliding last tick label)
    step = max(1, n // 6)
    tick_idxs = list(range(0, n, step))
    if (n - 1) not in tick_idxs:
        if tick_idxs and ((n - 1) - tick_idxs[-1]) < max(2, step // 2):
            tick_idxs[-1] = n - 1
        else:
            tick_idxs.append(n - 1)
    ax.set_xticks(tick_idxs)
    ax.set_xticklabels([to_bangkok(bar_times[i]).strftime("%H:%M") for i in tick_idxs], color="#94a3b8", fontsize=8)
    ax.tick_params(colors="#94a3b8")
    ax.yaxis.tick_right()
    ax.grid(True, linestyle="--", alpha=0.14, color="#64748b")
    for spine in ax.spines.values():
        spine.set_color("#2a2e39")

    ax.set_xlim(-1, right_ext + 0.5)
    ax.set_ylim(y_min, y_max)
    ax.legend(loc="upper left", facecolor="#1e222d", edgecolor="#334155", labelcolor="#e2e8f0", fontsize=7.8)
    ax.set_title(panel_title, color="#f8fafc", fontsize=10.5, fontweight="bold", pad=8)


def render_gold_ai_chart(
    symbol: str,
    bars_15m: List[Bar],
    bars_5m: List[Bar],
    setup_data: Dict[str, Any],
    event_tag: str = "CONTEXT",
    planned_trade: Optional[Dict[str, Any]] = None,
    ai_note: str = "",
    extra_audit: Optional[Dict[str, Any]] = None,
    base_screenshots_dir: Optional[Path] = None,
) -> Dict[str, str]:
    """
    Render M15 (80 bars) + M5 (40 bars) side-by-side chart with Base-anchored zones
    and save both .png and companion .json audit record under screenshots/ai_trader/YYYY-MM-DD/.
    """
    now_bkk = datetime.now(TZ_BANGKOK)
    root_dir = (base_screenshots_dir or settings.screenshots_dir) / "ai_trader" / now_bkk.strftime("%Y-%m-%d")
    root_dir.mkdir(parents=True, exist_ok=True)

    safe_tag = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in event_tag.upper())[:32]
    fname_base = f"{symbol}_AI_{now_bkk.strftime('%H-%M-%S')}_{safe_tag}"
    img_path = root_dir / f"{fname_base}.png"
    json_path = root_dir / f"{fname_base}.json"

    curr_px = float(setup_data.get("current_price") or (bars_5m[-1].close if bars_5m else 0.0))
    demands = setup_data.get("demand_zones", [])
    supplies = setup_data.get("supply_zones", [])
    m5_zmap = extract_fresh_m5_zones(bars_5m, curr_px, float(setup_data.get("current_atr") or 3.0))
    m5_panel_demands = m5_zmap["m5_demand_zones"] + list(demands)
    m5_panel_supplies = m5_zmap["m5_supply_zones"] + list(supplies)
    fibo_buy = setup_data.get("fibo_buy") or {}
    fibo_sell = setup_data.get("fibo_sell") or {}

    fig, (ax_m15, ax_m5) = plt.subplots(
        1, 2, figsize=(16, 7.2), gridspec_kw={"width_ratios": [1.25, 1.0], "wspace": 0.12}, facecolor="#0d1117"
    )
    try:
        _draw_candlestick_panel(
            ax=ax_m15,
            bars=bars_15m[-80:],
            all_bars_for_ma=bars_15m,
            demands=demands,
            supplies=supplies,
            fibo_buy=fibo_buy,
            fibo_sell=fibo_sell,
            current_price=curr_px,
            panel_title=f"{symbol} [M15 Structure - 80 Bars] | ATR: ${setup_data.get('current_atr', 0):.2f}",
            planned_trade=planned_trade,
        )
        _draw_candlestick_panel(
            ax=ax_m5,
            bars=bars_5m[-40:],
            all_bars_for_ma=bars_5m,
            demands=m5_panel_demands,
            supplies=m5_panel_supplies,
            fibo_buy=fibo_buy,
            fibo_sell=fibo_sell,
            current_price=curr_px,
            panel_title=f"{symbol} [M5 Sniper - 40 Bars] | Last: ${curr_px:.2f} | BKK {now_bkk.strftime('%H:%M:%S')}",
            planned_trade=planned_trade,
        )
        fig.suptitle(
            f"AI TRADER VISUAL AUDIT — {symbol} ({safe_tag})  |  Note: {ai_note or 'Structure & Chop Inspection'}",
            color="#f1f5f9",
            fontsize=11.5,
            fontweight="bold",
            y=0.98,
        )
        plt.savefig(img_path, facecolor="#0d1117", bbox_inches="tight", dpi=130)
    finally:
        plt.close(fig)

    audit_payload: Dict[str, Any] = {
        "timestamp_bkk": now_bkk.isoformat(),
        "symbol": symbol,
        "event_tag": safe_tag,
        "image_path": str(img_path.resolve()),
        "current_price": curr_px,
        "spread": setup_data.get("spread"),
        "atr_15m": setup_data.get("current_atr"),
        "ai_note": ai_note,
        "planned_trade": planned_trade,
        "nearest_demand": setup_data.get("nearest_demand"),
        "nearest_supply": setup_data.get("nearest_supply"),
    }
    if extra_audit:
        audit_payload.update(extra_audit)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(audit_payload, f, indent=2, ensure_ascii=False)

    return {
        "image_path": str(img_path.resolve()),
        "audit_json_path": str(json_path.resolve()),
    }


def _evaluate_approach_momentum(bars_5m: List[Bar], curr_atr: float) -> Dict[str, Any]:
    """
    Evaluate real-time M5 approach velocity so AI Trader knows immediately whether it is
    SAFE_TO_LIMIT (normal pullback/base) vs FAST_IMPULSE_WAIT (falling knife / rocket surge).
    """
    m5_atr = max(curr_atr * 0.60, 0.80)
    if not bars_5m:
        return {
            "buy_side_status": "SAFE_TO_LIMIT",
            "sell_side_status": "SAFE_TO_LIMIT",
            "max_recent_m5_range_x_atr": 0.0,
            "live_m5_range_x_atr": 0.0,
            "reason": "No M5 bars available — default safe",
        }

    recent_2 = bars_5m[-2:] if len(bars_5m) >= 2 else bars_5m[-1:]
    recent_3 = bars_5m[-3:] if len(bars_5m) >= 3 else recent_2
    live_b = bars_5m[-1]
    live_rng = max(live_b.high - live_b.low, 0.0)
    live_x_atr = round(live_rng / m5_atr, 2)
    max_recent_x_atr = round(max((max(b.high - b.low, 0.0) / m5_atr) for b in recent_2), 2)

    def _is_bear_impulse(b: Bar) -> bool:
        rng = max(b.high - b.low, 0.001)
        body = b.open - b.close  # positive when bearish
        return (body > 0) and ((rng / m5_atr) >= 1.50) and ((body / rng) >= 0.65)

    def _is_bull_impulse(b: Bar) -> bool:
        rng = max(b.high - b.low, 0.001)
        body = b.close - b.open  # positive when bullish
        return (body > 0) and ((rng / m5_atr) >= 1.50) and ((body / rng) >= 0.65)

    drop_3 = recent_3[0].open - recent_3[-1].close
    bear_streak_3 = all(b.close < b.open for b in recent_3) and len(recent_3) == 3
    severe_drop_3 = (drop_3 >= curr_atr * 1.80) and (bear_streak_3 or drop_3 >= curr_atr * 2.30)

    surge_3 = recent_3[-1].close - recent_3[0].open
    bull_streak_3 = all(b.close > b.open for b in recent_3) and len(recent_3) == 3
    severe_surge_3 = (surge_3 >= curr_atr * 1.80) and (bull_streak_3 or surge_3 >= curr_atr * 2.30)

    fast_bear = any(_is_bear_impulse(b) for b in recent_2) or severe_drop_3
    fast_bull = any(_is_bull_impulse(b) for b in recent_2) or severe_surge_3

    buy_status = "FAST_IMPULSE_WAIT" if fast_bear else "SAFE_TO_LIMIT"
    sell_status = "FAST_IMPULSE_WAIT" if fast_bull else "SAFE_TO_LIMIT"

    reasons = []
    if fast_bear:
        reasons.append(f"M5 แรงเทขายทุบเร็ว (max_range={max_recent_x_atr:.2f}x M5_ATR, 3-bar drop=${drop_3:.2f}) รอจบแท่ง M5 ก่อนดัก Buy")
    if fast_bull:
        reasons.append(f"M5 แรงซื้อพุ่งแรง (max_range={max_recent_x_atr:.2f}x M5_ATR, 3-bar surge=${surge_3:.2f}) รอจบแท่ง M5 ก่อนดัก Sell")
    if not reasons:
        reasons.append(f"ความเร็วแท่ง M5 ปกติ (max_range={max_recent_x_atr:.2f}x M5_ATR < 1.50) สามารถวาง Limit ดักโซนได้ทันที")

    return {
        "buy_side_status": buy_status,
        "sell_side_status": sell_status,
        "max_recent_m5_range_x_atr": max_recent_x_atr,
        "live_m5_range_x_atr": live_x_atr,
        "three_bar_drop_usd": round(drop_3, 2),
        "three_bar_surge_usd": round(surge_3, 2),
        "reason": "; ".join(reasons),
    }


def extract_fresh_m5_zones(
    bars_5m: List[Bar],
    curr_price: float,
    curr_atr: float,
) -> Dict[str, Any]:
    """
    Detect fresh M5 Demand/Supply sub-structure zones (retest_count <= 1, unbroken)
    so Radar & AI Trader do not miss intraday setups inside wide M15/H1 ranges.
    """
    if not bars_5m or len(bars_5m) < 15:
        return {
            "m5_demand_zones": [],
            "m5_supply_zones": [],
            "nearest_m5_demand": None,
            "nearest_m5_supply": None,
        }

    m5_atr = max(curr_atr * 0.60, 0.80)
    raw = detect_demand_supply_zones(bars_5m, min_bars=15, timeframe_label="5m", atr_val=m5_atr)
    fresh_demands = [
        z for z in raw.get("demand_zones", [])
        if int(z.get("retest_count", 0)) <= 1 and not z.get("is_broken")
    ]
    fresh_supplies = [
        z for z in raw.get("supply_zones", [])
        if int(z.get("retest_count", 0)) <= 1 and not z.get("is_broken")
    ]

    valid_d = [
        z for z in fresh_demands
        if curr_price <= 0 or float(z["zone_low"]) <= (curr_price + 0.25 * m5_atr)
    ]
    valid_s = [
        z for z in fresh_supplies
        if curr_price <= 0 or float(z["zone_high"]) >= (curr_price - 0.25 * m5_atr)
    ]

    def _dist_to_zone(z: Dict[str, Any]) -> float:
        zl, zh = float(z["zone_low"]), float(z["zone_high"])
        if zl <= curr_price <= zh:
            return 0.0
        return min(abs(curr_price - zl), abs(curr_price - zh))

    nearest_d = min(valid_d, key=_dist_to_zone) if (valid_d and curr_price > 0) else (valid_d[-1] if valid_d else None)
    nearest_s = min(valid_s, key=_dist_to_zone) if (valid_s and curr_price > 0) else (valid_s[-1] if valid_s else None)

    return {
        "m5_demand_zones": fresh_demands[-3:],
        "m5_supply_zones": fresh_supplies[-3:],
        "nearest_m5_demand": nearest_d,
        "nearest_m5_supply": nearest_s,
    }


def _zone_has_golden_confluence(
    zone: Dict[str, Any],
    fibo_data: Optional[Dict[str, Any]],
) -> bool:
    """Return True when a Demand/Supply zone overlaps the Fibo Golden Zone or contains fibo_650/fibo_618."""
    conf = zone.get("fibo_confluence") or {}
    if conf.get("has_confluence"):
        return True
    if not isinstance(fibo_data, dict):
        return False
    zl, zh = float(zone["zone_low"]), float(zone["zone_high"])
    for key in ("fibo_650", "fibo_618"):
        val = fibo_data.get(key)
        if val is not None and zl <= float(val) <= zh:
            return True
    return False


def _zone_has_ok_fibo_or_h1_rr(
    zone: Dict[str, Any],
    fibo_data: Optional[Dict[str, Any]],
) -> tuple[bool, Optional[float], str]:
    """
    Check if zone has at least Trend Pullback Fibo (38.2%-61.8%, covering 38.2% & 50.0%)
    or H1 Role Reversal support.
    Returns (is_supported, preferred_fibo_level_or_none, reason_tag).
    """
    if zone.get("is_h1_role_reversal"):
        return True, None, "H1_ROLE_REVERSAL"
    conf = zone.get("fibo_confluence") or {}
    zl, zh = float(zone["zone_low"]), float(zone["zone_high"])
    if conf.get("has_ok_fibo") or conf.get("fibo_tier") in ("GOLDEN_ZONE", "TREND_PULLBACK"):
        tlv = conf.get("fibo_target_level") or conf.get("overlap_mid")
        if tlv is not None and zl <= float(tlv) <= zh:
            return True, round(float(tlv), 2), "TREND_PULLBACK_FIBO"
        return True, None, "TREND_PULLBACK_FIBO"

    if isinstance(fibo_data, dict):
        f382 = fibo_data.get("fibo_382")
        f500 = fibo_data.get("fibo_500")
        f618 = fibo_data.get("fibo_618")
        if f500 is not None and zl <= float(f500) <= zh:
            return True, round(float(f500), 2), "TREND_PULLBACK_FIBO"
        if f382 is not None and zl <= float(f382) <= zh:
            return True, round(float(f382), 2), "TREND_PULLBACK_FIBO"
        if f382 is not None and f618 is not None:
            pb_low = min(float(f382), float(f618))
            pb_high = max(float(f382), float(f618))
            ov_low = max(zl, pb_low)
            ov_high = min(zh, pb_high)
            if ov_high >= ov_low:
                return True, round((ov_low + ov_high) / 2.0, 2), "TREND_PULLBACK_FIBO"
    return False, None, "NO_FIBO_SUPPORT"


def _evaluate_zone_limit_candidate(
    zone: Dict[str, Any],
    direction: str,
    curr_price: float,
    safe_atr: float,
    moat: float,
    spread: float,
    fibo_data: Optional[Dict[str, Any]],
    opp_zone: Optional[Dict[str, Any]],
    entry_tier: str,
    shifted_from_nearest: bool,
) -> Dict[str, Any]:
    """Compute a Hard-Risk-Gate-evaluated Limit candidate for a Demand (BUY) or Supply (SELL) zone."""
    zl, zh = float(zone["zone_low"]), float(zone["zone_high"])
    width = max(zh - zl, 0.0)
    zmid = round((zl + zh) / 2.0, 2)
    conf = zone.get("fibo_confluence") or {}
    has_conf = _zone_has_golden_confluence(zone, fibo_data)
    has_ok_fibo, pb_target, support_tag = _zone_has_ok_fibo_or_h1_rr(zone, fibo_data)
    is_double = bool(conf.get("double_confluence", False))
    fibo_supported = bool(has_conf or has_ok_fibo or entry_tier != "NO_FIBO_SUPPORT")
    gate_reason = "OK"

    if entry_tier in ("GOLDEN_ZONE_CONFLUENCE", "NEARBY_GOLDEN_ZONE_SHIFT"):
        ov_low = float(conf.get("overlap_low", zl))
        ov_high = float(conf.get("overlap_high", zh))
        f65 = conf.get("fibo_650") or (fibo_data.get("fibo_650") if isinstance(fibo_data, dict) else None)
        f618 = fibo_data.get("fibo_618") if isinstance(fibo_data, dict) else None
        if f65 is not None and ov_low <= float(f65) <= ov_high and zl <= float(f65) <= zh:
            raw_entry = round(float(f65), 2)
        elif f618 is not None and ov_low <= float(f618) <= ov_high and zl <= float(f618) <= zh:
            raw_entry = round(float(f618), 2)
        elif conf.get("overlap_mid") is not None:
            raw_entry = round(float(conf["overlap_mid"]), 2)
        else:
            raw_entry = zmid
        confirmation_policy = "IMMEDIATE_LIMIT_RELAXED"
    elif entry_tier in ("TREND_PULLBACK_FIBO", "NEARBY_PULLBACK_FIBO_SHIFT", "H1_ROLE_REVERSAL"):
        if pb_target is not None and zl <= pb_target <= zh:
            raw_entry = pb_target
        else:
            depth_ratio = 0.35
            raw_entry = round(zl + width * depth_ratio, 2) if direction == "BUY" else round(zh - width * depth_ratio, 2)
        confirmation_policy = "LIMIT_H1_ROLE_REVERSAL" if support_tag == "H1_ROLE_REVERSAL" else "LIMIT_FIBO_PULLBACK_WITH_KNIFE_GUARD"
    else:
        depth_ratio = 0.35
        raw_entry = round(zl + width * depth_ratio, 2) if direction == "BUY" else round(zh - width * depth_ratio, 2)
        confirmation_policy = "BLOCKED_SHALLOW_NO_FIBO"
        fibo_supported = False
        gate_reason = "ไม่มีแนว Fibo 38.2%-78.6% หรือ H1 Role Reversal รองรับ (โซนตื้นเกินไป ห้ามตั้ง Blind Limit)"

    if direction == "BUY":
        sl = round(zl - moat, 2)
        safe_bound = round(sl + MAX_GOLD_SL_USD - 0.05, 2)
        entry = round(min(raw_entry, safe_bound, zh), 2)
        if (entry - sl) < MIN_GOLD_SL_USD:
            sl = round(entry - MIN_GOLD_SL_USD, 2)
        sl_dist = round(entry - sl, 2)
        clamped_to_sl_cap = (raw_entry - entry) > 2.50
        if clamped_to_sl_cap:
            gate_reason = "โซนกว้างเกินเพดาน SL $8.00 (จุดเข้าถูกบีบหลุดแนว Fibo — ให้รอ micro_buy_limit บนฐาน M5 แทน)"
        tp_cap = (
            round(float(opp_zone["zone_low"]) - min(safe_atr * 0.25, 1.50), 2)
            if opp_zone and float(opp_zone["zone_low"]) > entry
            else round(entry + sl_dist * 2.2, 2)
        )
        tp = round(min(entry + max(sl_dist * 2.0, 3.0), tp_cap), 2)
        rr = round((tp - entry) / sl_dist, 2) if sl_dist > 0 else 0.0
        side_valid = bool(curr_price <= 0 or entry < curr_price)
        return {
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "sl_distance_usd": sl_dist,
            "rr_ratio": rr,
            "max_safe_entry_for_8usd_sl": safe_bound,
            "clamped_to_sl_cap": clamped_to_sl_cap,
            "below_current_price": side_valid,
            "passes_hard_gate": bool(
                fibo_supported
                and (not clamped_to_sl_cap)
                and side_valid
                and (MIN_GOLD_SL_USD <= sl_dist <= MAX_GOLD_SL_USD)
                and (rr >= MIN_GOLD_RR_RATIO)
                and (zl <= entry <= zh)
            ),
            "gate_reason": gate_reason,
            "entry_tier": entry_tier,
            "has_fibo_confluence": has_conf,
            "has_ok_fibo": bool(has_conf or has_ok_fibo),
            "double_confluence": is_double,
            "shifted_from_nearest": shifted_from_nearest,
            "confirmation_policy": confirmation_policy,
            "zone_low": round(zl, 2),
            "zone_high": round(zh, 2),
            "zone_label": zone.get("label"),
        }

    sl = round(zh + moat + max(spread, 0.0), 2)
    safe_bound = round(sl - MAX_GOLD_SL_USD + 0.05, 2)
    entry = round(max(raw_entry, safe_bound, zl), 2)
    if (sl - entry) < MIN_GOLD_SL_USD:
        sl = round(entry + MIN_GOLD_SL_USD, 2)
    sl_dist = round(sl - entry, 2)
    clamped_to_sl_cap = (entry - raw_entry) > 2.50
    if clamped_to_sl_cap:
        gate_reason = "โซนกว้างเกินเพดาน SL $8.00 (จุดเข้าถูกบีบหลุดแนว Fibo — ให้รอ micro_sell_limit บนฐาน M5 แทน)"
    tp_cap = (
        round(float(opp_zone["zone_high"]) + min(safe_atr * 0.25, 1.50), 2)
        if opp_zone and float(opp_zone["zone_high"]) < entry
        else round(entry - sl_dist * 2.2, 2)
    )
    tp = round(max(entry - max(sl_dist * 2.0, 3.0), tp_cap), 2)
    rr = round((entry - tp) / sl_dist, 2) if sl_dist > 0 else 0.0
    side_valid = bool(curr_price <= 0 or entry > curr_price)
    return {
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "sl_distance_usd": sl_dist,
        "rr_ratio": rr,
        "min_safe_entry_for_8usd_sl": safe_bound,
        "clamped_to_sl_cap": clamped_to_sl_cap,
        "above_current_price": side_valid,
        "passes_hard_gate": bool(
            fibo_supported
            and (not clamped_to_sl_cap)
            and side_valid
            and (MIN_GOLD_SL_USD <= sl_dist <= MAX_GOLD_SL_USD)
            and (rr >= MIN_GOLD_RR_RATIO)
            and (zl <= entry <= zh)
        ),
        "gate_reason": gate_reason,
        "entry_tier": entry_tier,
        "has_fibo_confluence": has_conf,
        "has_ok_fibo": bool(has_conf or has_ok_fibo),
        "double_confluence": is_double,
        "shifted_from_nearest": shifted_from_nearest,
        "confirmation_policy": confirmation_policy,
        "zone_low": round(zl, 2),
        "zone_high": round(zh, 2),
        "zone_label": zone.get("label"),
    }


def _select_fibo_prioritized_zone_candidate(
    primary_zone: Optional[Dict[str, Any]],
    all_zones: List[Dict[str, Any]],
    direction: str,
    curr_price: float,
    safe_atr: float,
    moat: float,
    spread: float,
    fibo_data: Optional[Dict[str, Any]],
    opp_zone: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    4-Tier Fibo-Guarded Limit-First selection:
    1) GOLDEN_ZONE_CONFLUENCE: primary zone overlaps Fibo Golden Zone (61.8% - 78.6%).
    2) NEARBY_GOLDEN_ZONE_SHIFT: nearby zone (<= max(1.5x ATR, $10)) overlaps Fibo Golden Zone and passes Hard Gate.
    3) TREND_PULLBACK_FIBO / H1_ROLE_REVERSAL: primary (or nearby <= 1.5x ATR) zone overlaps Fibo 38.2%-61.8% or H1 Role Reversal.
    4) NO_FIBO_SUPPORT: shallow zone without Fibo 38.2%-78.6% or H1 Role Reversal -> blocked (passes_hard_gate=False).
    """
    if not primary_zone:
        return None

    if _zone_has_golden_confluence(primary_zone, fibo_data):
        return _evaluate_zone_limit_candidate(
            zone=primary_zone,
            direction=direction,
            curr_price=curr_price,
            safe_atr=safe_atr,
            moat=moat,
            spread=spread,
            fibo_data=fibo_data,
            opp_zone=opp_zone,
            entry_tier="GOLDEN_ZONE_CONFLUENCE",
            shifted_from_nearest=False,
        )

    max_shift_dist = max(1.50 * safe_atr, 10.0)
    nearby_golden: List[tuple[float, Dict[str, Any]]] = []
    nearby_pullback: List[tuple[float, Dict[str, Any], str]] = []
    for z in all_zones or []:
        if z is primary_zone or (
            float(z["zone_low"]) == float(primary_zone["zone_low"])
            and float(z["zone_high"]) == float(primary_zone["zone_high"])
        ):
            continue
        zl, zh = float(z["zone_low"]), float(z["zone_high"])
        if curr_price > 0:
            if direction == "BUY" and zl >= curr_price:
                continue
            if direction == "SELL" and zh <= curr_price:
                continue
            dist = max(0.0, curr_price - zh) if direction == "BUY" else max(0.0, zl - curr_price)
            if dist > max_shift_dist:
                continue
        else:
            dist = 0.0

        if _zone_has_golden_confluence(z, fibo_data):
            nearby_golden.append((dist, z))
        else:
            ok_pb, _, pb_tag = _zone_has_ok_fibo_or_h1_rr(z, fibo_data)
            if ok_pb:
                nearby_pullback.append((dist, z, pb_tag))

    nearby_golden.sort(key=lambda item: item[0])
    for _, nz in nearby_golden:
        cand = _evaluate_zone_limit_candidate(
            zone=nz,
            direction=direction,
            curr_price=curr_price,
            safe_atr=safe_atr,
            moat=moat,
            spread=spread,
            fibo_data=fibo_data,
            opp_zone=opp_zone,
            entry_tier="NEARBY_GOLDEN_ZONE_SHIFT",
            shifted_from_nearest=True,
        )
        if cand["passes_hard_gate"]:
            return cand

    prim_ok, _, prim_tag = _zone_has_ok_fibo_or_h1_rr(primary_zone, fibo_data)
    if prim_ok:
        tier_name = "H1_ROLE_REVERSAL" if prim_tag == "H1_ROLE_REVERSAL" else "TREND_PULLBACK_FIBO"
        return _evaluate_zone_limit_candidate(
            zone=primary_zone,
            direction=direction,
            curr_price=curr_price,
            safe_atr=safe_atr,
            moat=moat,
            spread=spread,
            fibo_data=fibo_data,
            opp_zone=opp_zone,
            entry_tier=tier_name,
            shifted_from_nearest=False,
        )

    nearby_pullback.sort(key=lambda item: item[0])
    for _, nz, pb_tag in nearby_pullback:
        cand = _evaluate_zone_limit_candidate(
            zone=nz,
            direction=direction,
            curr_price=curr_price,
            safe_atr=safe_atr,
            moat=moat,
            spread=spread,
            fibo_data=fibo_data,
            opp_zone=opp_zone,
            entry_tier="H1_ROLE_REVERSAL" if pb_tag == "H1_ROLE_REVERSAL" else "NEARBY_PULLBACK_FIBO_SHIFT",
            shifted_from_nearest=True,
        )
        if cand["passes_hard_gate"]:
            return cand

    return _evaluate_zone_limit_candidate(
        zone=primary_zone,
        direction=direction,
        curr_price=curr_price,
        safe_atr=safe_atr,
        moat=moat,
        spread=spread,
        fibo_data=fibo_data,
        opp_zone=opp_zone,
        entry_tier="NO_FIBO_SUPPORT",
        shifted_from_nearest=False,
    )


def _build_limit_entry_candidates(
    curr_price: float,
    curr_atr: float,
    spread: float,
    nearest_demand: Optional[Dict[str, Any]],
    nearest_supply: Optional[Dict[str, Any]],
    fibo_buy: Optional[Dict[str, Any]],
    fibo_sell: Optional[Dict[str, Any]],
    bars_5m: List[Bar],
    nearest_m5_demand: Optional[Dict[str, Any]] = None,
    nearest_m5_supply: Optional[Dict[str, Any]] = None,
    demand_zones: Optional[List[Dict[str, Any]]] = None,
    supply_zones: Optional[List[Dict[str, Any]]] = None,
    trend_indicators: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Pre-calculate Hard-Risk-Gate-compliant Limit prices inside Demand/Supply zones
    so AI Trader can pre-place optimal Limit entries (SL <= $8.00, R:R >= 1.50) without missing moves.
    Prioritizes Fibo Golden Zone confluence (Tier 1), nearby Golden Zone shift (Tier 2),
    and deep-zone discount placement (Tier 3), plus micro/M5 limits for wide ranges.
    """
    out: Dict[str, Any] = {
        "buy_limit_zone": None,
        "micro_buy_limit": None,
        "m5_buy_limit_zone": None,
        "sell_limit_zone": None,
        "micro_sell_limit": None,
        "m5_sell_limit_zone": None,
        "last_closed_m5_retrace_50": None,
    }
    safe_atr = max(curr_atr, 1.0)
    moat = min(max(safe_atr * 0.18, 0.80), 1.80)
    micro_moat = min(max(safe_atr * 0.14, 0.80), 1.50)

    ti = trend_indicators or {}
    m15_tr = str(ti.get("trend", "NEUTRAL")).upper()
    h1_tr = str(ti.get("h1_trend", "NEUTRAL")).upper()
    strong_bull = (h1_tr == "BULLISH" and m15_tr == "BULLISH")
    strong_bear = (h1_tr == "BEARISH" and m15_tr == "BEARISH")
    m15_struct = ti.get("m15_structure") or {}
    m15_choch_bear = str(m15_struct.get("live_break", "NONE")).upper() == "CHOCH_BEAR"
    m15_choch_bull = str(m15_struct.get("live_break", "NONE")).upper() == "CHOCH_BULL"

    if nearest_demand:
        zl, zh = float(nearest_demand["zone_low"]), float(nearest_demand["zone_high"])
        buy_cand = _select_fibo_prioritized_zone_candidate(
            primary_zone=nearest_demand,
            all_zones=demand_zones or [],
            direction="BUY",
            curr_price=curr_price,
            safe_atr=safe_atr,
            moat=moat,
            spread=spread,
            fibo_data=fibo_buy,
            opp_zone=nearest_supply,
        )
        if buy_cand and strong_bear:
            buy_cand["passes_hard_gate"] = False
            buy_cand["gate_reason"] = "ห้ามวาง Blind Buy Limit สวนเทรนด์หลักขาลง (H1+M15 BEARISH) — ต้องรอแท่งกลับตัวเท่านั้น"
            buy_cand["confirmation_policy"] = "BLOCKED_COUNTER_TREND_BLIND_LIMIT"
        elif buy_cand and m15_choch_bear:
            buy_cand["passes_hard_gate"] = False
            buy_cand["gate_reason"] = "ห้ามวาง Blind Buy Limit: M15 เพิ่งปิดแท่งเสียโครงสร้างขาขึ้น (CHoCH Bearish หลุด Swing Low ล่าสุด) — ต้องรอแท่งยืนยันการกลับตัวเท่านั้น"
            buy_cand["confirmation_policy"] = "BLOCKED_M15_CHOCH_COUNTER_TREND"
        out["buy_limit_zone"] = buy_cand
        entry = buy_cand["entry"]

        # Micro-Structure Buy Limit for Wide Demand Zones (> $8 width or deep entry > $6 away while near/in zone)
        in_or_near_demand = curr_price > 0 and (zl - 0.20 * safe_atr) <= curr_price <= (zh + 0.80 * safe_atr)
        zone_width = zh - zl
        if in_or_near_demand and bars_5m and (zone_width > 7.50 or (curr_price - entry) > 6.50):
            recent_m5 = bars_5m[-8:] if len(bars_5m) >= 3 else bars_5m
            local_low = min(b.low for b in recent_m5)
            # Only valid if local M5 base formed near or inside the demand zone and below current price
            if (zl - 1.50) <= local_low < (curr_price - 0.40):
                m_sl = round(local_low - micro_moat, 2)
                m_max_entry = round(m_sl + MAX_GOLD_SL_USD - 0.05, 2)
                # Target a shallow 35-45% pullback toward local_low so we get filled without missing the bounce
                ideal_pullback = round(local_low + (curr_price - local_low) * 0.55, 2)
                max_below_curr = round(curr_price - max(spread + 0.25, 0.50), 2)
                m_entry = round(min(ideal_pullback, m_max_entry, max_below_curr, zh + 1.00), 2)
                m_sl_dist = round(m_entry - m_sl, 2)
                m_tp_cap = (
                    round(float(nearest_supply["zone_low"]) - min(safe_atr * 0.25, 1.50), 2)
                    if nearest_supply and float(nearest_supply["zone_low"]) > m_entry
                    else round(m_entry + max(m_sl_dist * 2.0, 4.0), 2)
                )
                m_tp = round(min(m_entry + max(m_sl_dist * 2.0, 3.0), m_tp_cap), 2)
                m_rr = round((m_tp - m_entry) / m_sl_dist, 2) if m_sl_dist > 0 else 0.0
                out["micro_buy_limit"] = {
                    "anchor_m5_low": round(local_low, 2),
                    "entry": m_entry,
                    "sl": m_sl,
                    "tp": m_tp,
                    "sl_distance_usd": m_sl_dist,
                    "rr_ratio": m_rr,
                    "below_current_price": bool(m_entry < curr_price),
                    "passes_hard_gate": bool(
                        (m_entry < curr_price)
                        and (0.20 <= m_sl_dist <= MAX_GOLD_SL_USD)
                        and (m_rr >= MIN_GOLD_RR_RATIO)
                    ),
                    "note": f"ดักย่อฐาน M5 ในโซนกว้าง (SL ใต้ Low ย่อย ${local_low:.2f})",
                }

    if nearest_supply:
        zl, zh = float(nearest_supply["zone_low"]), float(nearest_supply["zone_high"])
        sell_cand = _select_fibo_prioritized_zone_candidate(
            primary_zone=nearest_supply,
            all_zones=supply_zones or [],
            direction="SELL",
            curr_price=curr_price,
            safe_atr=safe_atr,
            moat=moat,
            spread=spread,
            fibo_data=fibo_sell,
            opp_zone=nearest_demand,
        )
        out["sell_limit_zone"] = sell_cand
        if sell_cand and strong_bull:
            sell_cand["passes_hard_gate"] = False
            sell_cand["gate_reason"] = "ห้ามวาง Blind Sell Limit สวนเทรนด์หลักขาขึ้น (H1+M15 BULLISH) — ต้องรอแท่งกลับตัวเท่านั้น"
            sell_cand["confirmation_policy"] = "BLOCKED_COUNTER_TREND_BLIND_LIMIT"
        elif sell_cand and m15_choch_bull:
            sell_cand["passes_hard_gate"] = False
            sell_cand["gate_reason"] = "ห้ามวาง Blind Sell Limit: M15 เพิ่งปิดแท่งเสียโครงสร้างขาลง (CHoCH Bullish ทะลุ Swing High ล่าสุด) — ต้องรอแท่งยืนยันการกลับตัวเท่านั้น"
            sell_cand["confirmation_policy"] = "BLOCKED_M15_CHOCH_COUNTER_TREND"
        entry = sell_cand["entry"]

        # Micro-Structure Sell Limit for Wide Supply Zones
        in_or_near_supply = curr_price > 0 and (zl - 0.80 * safe_atr) <= curr_price <= (zh + 0.20 * safe_atr)
        zone_width = zh - zl
        if in_or_near_supply and bars_5m and (zone_width > 7.50 or (entry - curr_price) > 6.50):
            recent_m5 = bars_5m[-8:] if len(bars_5m) >= 3 else bars_5m
            local_high = max(b.high for b in recent_m5)
            if (curr_price + 0.40) < local_high <= (zh + 1.50):
                m_sl = round(local_high + micro_moat + max(spread, 0.0), 2)
                m_min_entry = round(m_sl - MAX_GOLD_SL_USD + 0.05, 2)
                ideal_retest = round(local_high - (local_high - curr_price) * 0.55, 2)
                min_above_curr = round(curr_price + max(spread + 0.25, 0.50), 2)
                m_entry = round(max(ideal_retest, m_min_entry, min_above_curr, zl - 1.00), 2)
                m_sl_dist = round(m_sl - m_entry, 2)
                m_tp_cap = (
                    round(float(nearest_demand["zone_high"]) + min(safe_atr * 0.25, 1.50), 2)
                    if nearest_demand and float(nearest_demand["zone_high"]) < m_entry
                    else round(m_entry - max(m_sl_dist * 2.0, 4.0), 2)
                )
                m_tp = round(max(m_entry - max(m_sl_dist * 2.0, 3.0), m_tp_cap), 2)
                m_rr = round((m_entry - m_tp) / m_sl_dist, 2) if m_sl_dist > 0 else 0.0
                out["micro_sell_limit"] = {
                    "anchor_m5_high": round(local_high, 2),
                    "entry": m_entry,
                    "sl": m_sl,
                    "tp": m_tp,
                    "sl_distance_usd": m_sl_dist,
                    "rr_ratio": m_rr,
                    "above_current_price": bool(m_entry > curr_price),
                    "passes_hard_gate": bool(
                        (m_entry > curr_price)
                        and (0.20 <= m_sl_dist <= MAX_GOLD_SL_USD)
                        and (m_rr >= MIN_GOLD_RR_RATIO)
                    ),
                    "note": f"ดักเด้งต้านย่อย M5 ในโซนกว้าง (SL เหนือ High ย่อย ${local_high:.2f})",
                }

    if nearest_m5_demand:
        zl, zh = float(nearest_m5_demand["zone_low"]), float(nearest_m5_demand["zone_high"])
        sl = round(zl - micro_moat, 2)
        max_safe_entry = round(sl + MAX_GOLD_SL_USD - 0.05, 2)
        max_below_curr = round(curr_price - max(spread + 0.20, 0.40), 2) if curr_price > 0 else zh
        raw_entry = round(zl + (zh - zl) * 0.70, 2)
        entry = round(min(raw_entry, max_safe_entry, max_below_curr, zh), 2)
        sl_dist = round(entry - sl, 2)
        opp_supplies = [
            float(s["zone_low"]) for s in (nearest_m5_supply, nearest_supply)
            if s and float(s["zone_low"]) > entry
        ]
        tp_cap = (
            round(min(opp_supplies) - min(safe_atr * 0.20, 1.20), 2)
            if opp_supplies
            else round(entry + max(sl_dist * 2.0, 4.0), 2)
        )
        tp = round(min(entry + max(sl_dist * 2.0, 3.0), tp_cap), 2)
        rr = round((tp - entry) / sl_dist, 2) if sl_dist > 0 else 0.0
        out["m5_buy_limit_zone"] = {
            "pattern": nearest_m5_demand.get("pattern"),
            "zone_low": zl,
            "zone_high": zh,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "sl_distance_usd": sl_dist,
            "rr_ratio": rr,
            "below_current_price": bool(curr_price <= 0 or entry < curr_price),
            "passes_hard_gate": bool(
                (curr_price <= 0 or entry < curr_price)
                and (0.20 <= sl_dist <= MAX_GOLD_SL_USD)
                and (rr >= MIN_GOLD_RR_RATIO)
                and (entry > sl)
            ),
        }

    if nearest_m5_supply:
        zl, zh = float(nearest_m5_supply["zone_low"]), float(nearest_m5_supply["zone_high"])
        sl = round(zh + micro_moat + max(spread, 0.0), 2)
        min_safe_entry = round(sl - MAX_GOLD_SL_USD + 0.05, 2)
        min_above_curr = round(curr_price + max(spread + 0.20, 0.40), 2) if curr_price > 0 else zl
        raw_entry = round(zh - (zh - zl) * 0.70, 2)
        entry = round(max(raw_entry, min_safe_entry, min_above_curr, zl), 2)
        sl_dist = round(sl - entry, 2)
        opp_demands = [
            float(d["zone_high"]) for d in (nearest_m5_demand, nearest_demand)
            if d and float(d["zone_high"]) < entry
        ]
        tp_cap = (
            round(max(opp_demands) + min(safe_atr * 0.20, 1.20), 2)
            if opp_demands
            else round(entry - max(sl_dist * 2.0, 4.0), 2)
        )
        tp = round(max(entry - max(sl_dist * 2.0, 3.0), tp_cap), 2)
        rr = round((entry - tp) / sl_dist, 2) if sl_dist > 0 else 0.0
        out["m5_sell_limit_zone"] = {
            "pattern": nearest_m5_supply.get("pattern"),
            "zone_low": zl,
            "zone_high": zh,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "sl_distance_usd": sl_dist,
            "rr_ratio": rr,
            "above_current_price": bool(curr_price <= 0 or entry > curr_price),
            "passes_hard_gate": bool(
                (curr_price <= 0 or entry > curr_price)
                and (0.20 <= sl_dist <= MAX_GOLD_SL_USD)
                and (rr >= MIN_GOLD_RR_RATIO)
                and (entry < sl)
            ),
        }

    confirmed_m5 = [b for b in bars_5m if b.is_confirmed]
    if confirmed_m5:
        lb = confirmed_m5[-1]
        out["last_closed_m5_retrace_50"] = {
            "bkk_time": to_bangkok(lb.open_time).strftime("%Y-%m-%d %H:%M"),
            "high": round(lb.high, 2),
            "low": round(lb.low, 2),
            "mid_50_pct": round((lb.high + lb.low) / 2.0, 2),
        }
    return out


def build_gold_ai_context(
    include_chart: bool = False,
    event_tag: str = "CONTEXT",
    planned_trade: Optional[Dict[str, Any]] = None,
    note: str = "",
    adapter: Optional[MT5DataAdapter] = None,
    client: Optional[MT5Client] = None,
    setup_override: Optional[Dict[str, Any]] = None,
    bars_override: Optional[Dict[str, List[Bar]]] = None,
    base_screenshots_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Assemble complete raw market context for Antigravity AI Trader Mode:
    - Raw H1 / M15 / M5 candle arrays with objective wick/body/ATR telemetry
    - Active Demand & Supply Base map + Multi-Swing Fibonacci levels + Headroom
    - Live Account, Open Positions (with floating R-multiple), Pending Limits, and Last 5 Closed Trades
    - News / Rollover / Spread / Volatility safety status
    - Optional Base-anchored dual-panel visual chart saved to screenshots/ai_trader/YYYY-MM-DD/
    """
    adp = adapter or MT5DataAdapter()
    cli = client or mt5_client
    if cli is mt5_client and not cli.is_connected:
        cli.connect()

    setup = setup_override if setup_override is not None else scan_gold_setup()
    symbol = setup.get("mt5_symbol") or setup.get("symbol") or "XAUUSDc"
    curr_price = float(setup.get("current_price") or 0.0)
    curr_atr = float(setup.get("current_atr") or 3.0)
    spread = float(setup.get("spread") or 0.20)
    live_bar_range = float(setup.get("live_bar_range") or 0.0)

    if bars_override is not None:
        bars_h1 = bars_override.get("H1", [])
        bars_15m = bars_override.get("M15", [])
        bars_5m = bars_override.get("M5", [])
    else:
        bars_h1 = adp.get_bars(symbol, TimeFrame.H1, limit=60)
        bars_15m = adp.get_bars(symbol, TimeFrame.M15, limit=140)
        bars_5m = adp.get_bars(symbol, TimeFrame.M5, limit=100)

    if curr_price <= 0 and bars_5m:
        curr_price = round(bars_5m[-1].close, 2)

    # Intraday 8h / 24h High-Low & Headroom telemetry
    intraday_bars = bars_15m[-32:] if len(bars_15m) >= 4 else bars_5m[-40:]
    day_high = round(max((b.high for b in intraday_bars), default=curr_price), 2)
    day_low = round(min((b.low for b in intraday_bars), default=curr_price), 2)

    demands = setup.get("demand_zones", [])
    supplies = setup.get("supply_zones", [])
    nearest_demand = setup.get("nearest_demand")
    nearest_supply = setup.get("nearest_supply")
    m5_zone_map = extract_fresh_m5_zones(bars_5m, curr_price, curr_atr)

    above_supplies = [s for s in supplies if float(s["zone_low"]) > curr_price]
    below_demands = [d for d in demands if float(d["zone_high"]) < curr_price]
    upside_headroom = round((float(above_supplies[0]["zone_low"]) - curr_price), 2) if above_supplies else 999.0
    floor_candidates = ([float(below_demands[0]["zone_high"])] if below_demands else []) + (
        [day_low] if day_low < curr_price else []
    )
    downside_floor = max(floor_candidates, default=0.0)
    downside_headroom = round(curr_price - downside_floor, 2) if downside_floor > 0 else 999.0

    # Safety & Blackout Checks
    in_news, news_msg = is_news_blackout()
    in_rollover, roll_msg = is_rollover_blackout()
    spread_ok, spread_msg = is_spread_acceptable(spread, max_allowed_spread=0.40)
    vol_spike, vol_msg = is_volatility_spike(live_bar_range, curr_atr, spike_multiplier=1.8)

    # Portfolio & Open Gold Positions (with live R-multiple)
    open_positions = [
        p for p in (cli.get_open_positions() or [])
        if any(k in str(p.get("symbol", "")).upper() for k in ("XAU", "GOLD"))
    ]
    for p in open_positions:
        op = float(p.get("open_price") or 0.0)
        sl = float(p.get("sl") or 0.0)
        cp = float(p.get("current_price") or curr_price)
        init_risk = abs(op - sl) if sl > 0 else 0.0
        gain = (cp - op) if str(p.get("direction", "")).upper() == "BUY" else (op - cp)
        p["floating_r_multiple"] = round(gain / init_risk, 2) if init_risk > 0.10 else None

    pending_orders = [
        o for o in (cli.get_pending_orders() or [])
        if any(k in str(o.get("symbol", "")).upper() for k in ("XAU", "GOLD"))
    ]

    chart_artifacts = None
    if include_chart:
        chart_artifacts = render_gold_ai_chart(
            symbol=symbol,
            bars_15m=bars_15m,
            bars_5m=bars_5m,
            setup_data=setup,
            event_tag=event_tag,
            planned_trade=planned_trade,
            ai_note=note,
            base_screenshots_dir=base_screenshots_dir,
        )

    login = cli.account_info.get("login") if cli.account_info else setup.get("target_account", 434552387)
    locked_lot = 0.06 if login == 160219615 else 0.01

    return {
        "mode": "AI_TRADER_RAW_CONTEXT",
        "bkk_time": datetime.now(TZ_BANGKOK).strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "market_snapshot": {
            "current_price": curr_price,
            "spread_usd": spread,
            "atr_15m": curr_atr,
            "live_5m_bar_range": live_bar_range,
            "intraday_high": day_high,
            "intraday_low": day_low,
            "upside_headroom_usd": upside_headroom,
            "upside_headroom_x_atr": round(upside_headroom / curr_atr, 2) if upside_headroom < 900 and curr_atr > 0 else 99.0,
            "downside_headroom_usd": downside_headroom,
            "downside_headroom_x_atr": round(downside_headroom / curr_atr, 2) if downside_headroom < 900 and curr_atr > 0 else 99.0,
        },
        "safety_guards": {
            "can_open_new_trade": (not in_news) and (not in_rollover) and spread_ok and (len(open_positions) == 0),
            "news_blackout": {"active": in_news, "detail": news_msg},
            "rollover_blackout": {"active": in_rollover, "detail": roll_msg},
            "spread_guard": {"ok": spread_ok, "detail": spread_msg, "max_allowed": 0.40},
            "volatility_spike": {"active": vol_spike, "detail": vol_msg},
            "hard_rules": {
                "locked_volume_lot": locked_lot,
                "max_sl_distance_usd": 8.00,
                "min_rr_ratio": 1.50,
                "max_open_positions": 1,
                "visual_chart_rule": "Use chart image ONLY to check Sideway/Chop structure; NEVER estimate prices from image — use JSON numbers 100%.",
            },
        },
        "session_and_trend": {
            "session": setup.get("session_info", {}),
            "trend_indicators": setup.get("trend_indicators", {}),
        },
        "structure_map": {
            "nearest_demand": nearest_demand,
            "nearest_supply": nearest_supply,
            "nearest_m5_demand": m5_zone_map["nearest_m5_demand"],
            "nearest_m5_supply": m5_zone_map["nearest_m5_supply"],
            "active_demand_zones": demands[:4],
            "active_supply_zones": supplies[:4],
            "m5_demand_zones": m5_zone_map["m5_demand_zones"],
            "m5_supply_zones": m5_zone_map["m5_supply_zones"],
            "fibo_buy_discount": setup.get("fibo_buy"),
            "fibo_sell_premium": setup.get("fibo_sell"),
            "fibo_major": setup.get("major_fibo"),
            "fibo_history_swings": setup.get("fibo_history", []),
            "double_confluence_active": setup.get("double_confluence_active", False),
            "approach_momentum": _evaluate_approach_momentum(bars_5m, curr_atr),
            "limit_entry_candidates": _build_limit_entry_candidates(
                curr_price=curr_price,
                curr_atr=curr_atr,
                spread=spread,
                nearest_demand=nearest_demand,
                nearest_supply=nearest_supply,
                fibo_buy=setup.get("fibo_buy"),
                fibo_sell=setup.get("fibo_sell"),
                bars_5m=bars_5m,
                nearest_m5_demand=m5_zone_map["nearest_m5_demand"],
                nearest_m5_supply=m5_zone_map["nearest_m5_supply"],
                demand_zones=demands,
                supply_zones=supplies,
                trend_indicators=setup.get("trend_indicators"),
            ),
            "ea_advisory_reference": {
                "ea_status": setup.get("status"),
                "ea_reason": setup.get("setup_reason"),
                "note": "Advisory only — AI Trader decides independently within Hard Risk Gate.",
            },
        },
        "raw_candles": {
            "H1_last_8": summarize_candles(bars_h1, curr_atr * 2.0, limit=8),
            "M15_last_15": summarize_candles(bars_15m, curr_atr, limit=15),
            "M5_last_18": summarize_candles(bars_5m, curr_atr * 0.6, limit=18),
        },
        "portfolio_state": {
            "account": cli.account_info or {"login": login},
            "open_gold_positions": open_positions,
            "pending_gold_orders": pending_orders,
            "recent_5_closed_gold_trades": _get_recent_closed_trades(limit=5),
        },
        "chart_artifacts": chart_artifacts,
    }
