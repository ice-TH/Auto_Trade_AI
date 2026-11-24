import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

import matplotlib
matplotlib.use("Agg")  # Non-interactive, headless backend for safe background rendering
import matplotlib.pyplot as plt
import matplotlib.patches as patches

from config.settings import settings
from src.data.calendar_guard import TZ_UTC, TZ_BANGKOK, TZ_EASTERN, to_bangkok, to_eastern

class ScreenshotService:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or settings.screenshots_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_target_dir(self, dt: datetime, symbol: str, timeframe: str) -> Path:
        date_folder = dt.strftime("%Y-%m-%d")
        target = self.base_dir / date_folder / symbol / timeframe
        target.mkdir(parents=True, exist_ok=True)
        return target

    def capture_chart(
        self,
        symbol: str,
        timeframe: str,
        event_id: str,
        image_bytes: Optional[bytes] = None,
        bars_data: Optional[List[Dict[str, Any]]] = None,
        zones_data: Optional[List[Dict[str, Any]]] = None,
        notes: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Save high-fidelity screenshot and companion metadata JSON adhering to Section 10 specification.
        """
        now_utc = datetime.now(TZ_UTC)
        target_dir = self._get_target_dir(now_utc, symbol, timeframe)
        
        timestamp_str = now_utc.strftime("%Y-%m-%d_%H-%M-%S")
        filename_base = f"{symbol}_{timeframe}_{timestamp_str}_{event_id}"
        img_path = target_dir / f"{filename_base}.png"
        meta_path = target_dir / f"{filename_base}.json"

        # If frontend didn't upload canvas, render professional chart on server
        if not image_bytes or len(image_bytes) < 100:
            self._render_server_chart(img_path, symbol, timeframe, bars_data, zones_data)
        else:
            with open(img_path, "wb") as f:
                f.write(image_bytes)

        # Companion metadata JSON
        now_bkk = to_bangkok(now_utc)
        now_et = to_eastern(now_utc)

        metadata = {
            "file_name": img_path.name,
            "relative_path": str(img_path.relative_to(self.base_dir)).replace("\\", "/"),
            "symbol": symbol,
            "timeframe": timeframe,
            "event_id": event_id,
            "utc_time": now_utc.isoformat(),
            "bangkok_time": now_bkk.isoformat(),
            "eastern_time": now_et.isoformat(),
            "notes": notes or (extra_metadata.get("notes") if extra_metadata else None) or f"Automated snapshot captured for event {event_id}",
            "candle_count": len(bars_data) if bars_data else 0,
            "zones_count": len(zones_data) if zones_data else 0
        }
        if extra_metadata:
            metadata.update({k: v for k, v in extra_metadata.items() if k != "notes"})

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return metadata

    def _render_server_chart(
        self,
        output_path: Path,
        symbol: str,
        timeframe: str,
        bars: Optional[List[Dict[str, Any]]],
        zones: Optional[List[Dict[str, Any]]]
    ):
        """
        Render a publication-grade, detailed candlestick chart with volume, EMA lines,
        horizontal grid, and S/R zone bands using matplotlib.
        """
        if not bars:
            fig, ax = plt.subplots(figsize=(10, 5), facecolor="#131722")
            ax.set_facecolor("#131722")
            ax.text(0.5, 0.5, "No Chart Data Available", color="#787b86", ha="center", va="center", fontsize=14)
            plt.savefig(output_path, facecolor="#131722", bbox_inches="tight")
            plt.close(fig)
            return

        recent_bars = bars[-50:]  # Show last 50 candles for high detail
        n = len(recent_bars)

        # Setup figure with 2 subplots: Price (75%) and Volume (25%)
        fig, (ax_price, ax_vol) = plt.subplots(
            2, 1, figsize=(13, 7.5),
            gridspec_kw={"height_ratios": [3.2, 1], "hspace": 0.05},
            facecolor="#131722"
        )
        ax_price.set_facecolor("#131722")
        ax_vol.set_facecolor("#131722")

        opens = [b["open"] for b in recent_bars]
        highs = [b["high"] for b in recent_bars]
        lows = [b["low"] for b in recent_bars]
        closes = [b["close"] for b in recent_bars]
        volumes = [b.get("volume", 0) for b in recent_bars]

        # 1. Draw S/R Zone shaded bands
        if zones:
            for z in zones[:4]:
                zh = z.get("price_high", 0.0)
                zl = z.get("price_low", 0.0)
                z_type = z.get("zone_type", "SUPPORT")
                if zh > 0 and zl > 0:
                    color = "#00c076" if z_type == "SUPPORT" else "#ef4444"
                    ax_price.axhspan(zl, zh, color=color, alpha=0.18, zorder=1)
                    # Label on right
                    ax_price.text(n - 1, (zh + zl) / 2, f" {z_type}", color=color, fontsize=8.5, va="center", fontweight="bold")

        # 2. Draw Candlesticks & Volume
        width = 0.65
        for i in range(n):
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            vol = volumes[i]
            is_bull = c >= o
            color = "#089981" if is_bull else "#f23645"

            # Upper and Lower Wicks
            ax_price.plot([i, i], [l, h], color=color, linewidth=1.2, zorder=3)
            # Body
            lower = min(o, c)
            height = max(abs(c - o), 0.001)
            rect = patches.Rectangle(
                (i - width / 2, lower), width, height,
                facecolor=color, edgecolor=color, linewidth=0.5, zorder=4
            )
            ax_price.add_patch(rect)

            # Volume bar
            vol_color = "#089981" if is_bull else "#f23645"
            ax_vol.bar(i, vol, color=vol_color, width=width, alpha=0.75, zorder=2)

        # 3. Calculate and Plot MA(50) and EMA(15) - Custom User Moving Averages
        def calc_sma(series: List[float], period: int) -> List[Optional[float]]:
            res: List[Optional[float]] = []
            for idx in range(len(series)):
                if idx + 1 < period:
                    res.append(None)
                else:
                    res.append(sum(series[idx + 1 - period : idx + 1]) / float(period))
            return res

        def calc_ema(series: List[float], period: int) -> List[Optional[float]]:
            if not series:
                return []
            k = 2.0 / (period + 1.0)
            res = [series[0]]
            for val in series[1:]:
                res.append(val * k + res[-1] * (1.0 - k))
            return res

        # We compute MA across all available bars if provided, else on recent_bars
        all_closes = [b["close"] for b in bars] if bars and len(bars) >= n else closes
        sma50_all = calc_sma(all_closes, 50)
        sma200_all = calc_sma(all_closes, 200)
        ema15_all = calc_ema(all_closes, 15)

        # Slice to the matching recent n bars
        sma50 = sma50_all[-n:]
        sma200 = sma200_all[-n:]
        ema15 = ema15_all[-n:]

        # Plot MA 50 (Cyan/Blue) if available
        valid_50 = [(i, val) for i, val in enumerate(sma50) if val is not None]
        if valid_50:
            x_50, y_50 = zip(*valid_50)
            ax_price.plot(x_50, y_50, color="#38bdf8", linewidth=1.5, label="MA(50) Trend", zorder=5)

        # Plot EMA 15 (Amber/Gold Fast Line)
        valid_15 = [(i, val) for i, val in enumerate(ema15) if val is not None]
        if valid_15:
            x_15, y_15 = zip(*valid_15)
            ax_price.plot(x_15, y_15, color="#f59e0b", linewidth=1.4, linestyle="--", label="EMA(15) Fast", zorder=5)

        # Plot MA 200 (Purple/Major Trend) if available
        valid_200 = [(i, val) for i, val in enumerate(sma200) if val is not None]
        if valid_200:
            x_200, y_200 = zip(*valid_200)
            ax_price.plot(x_200, y_200, color="#a855f7", linewidth=1.6, label="MA(200) Major Trend", zorder=5)

        ax_price.legend(loc="upper left", facecolor="#1e222d", edgecolor="#2a2e39", labelcolor="#d1d4dc", fontsize=8.5)

        # 4. Formatter & X-Axis Time Labels
        time_labels = []
        for b in recent_bars:
            raw_time = b.get("time") or b.get("open_time")
            if isinstance(raw_time, (int, float)):
                dt = datetime.fromtimestamp(raw_time, tz=timezone.utc)
            elif isinstance(raw_time, str):
                try:
                    dt = datetime.fromisoformat(raw_time)
                except Exception:
                    dt = datetime.now()
            else:
                dt = datetime.now()
            
            # Format time by timeframe
            if timeframe in ["1m", "5m", "15m", "M1", "M5", "M15"]:
                time_labels.append(dt.strftime("%H:%M"))
            else:
                time_labels.append(dt.strftime("%d %b"))

        step = max(1, n // 8)
        ticks_idx = list(range(0, n, step))
        if (n - 1) not in ticks_idx:
            ticks_idx.append(n - 1)

        ax_vol.set_xticks(ticks_idx)
        ax_vol.set_xticklabels([time_labels[i] for i in ticks_idx], color="#787b86", fontsize=8.5)
        ax_price.set_xticks([])  # Hide top X ticks to align subplots

        # 5. Styling Grids & Y-Axes
        for ax in [ax_price, ax_vol]:
            ax.tick_params(colors="#787b86")
            ax.grid(True, linestyle="--", alpha=0.15, color="#787b86")
            ax.yaxis.tick_right()
            ax.yaxis.set_label_position("right")
            for spine in ax.spines.values():
                spine.set_color("#2a2e39")

        ax_price.set_xlim(-1, n + 2)
        ax_vol.set_xlim(-1, n + 2)
        ax_vol.set_ylabel("Volume", color="#787b86", fontsize=8.5)
        ax_price.set_ylabel("Price (USD)", color="#787b86", fontsize=9.5)

        # Header Title Banner
        now_bkk = datetime.now(TZ_BANGKOK).strftime("%Y-%m-%d %H:%M:%S")
        ax_price.set_title(
            f"AUTOTRADE PRO JOURNAL: {symbol} [{timeframe}]   |   BKK Time: {now_bkk}   |   Last: ${closes[-1]:.2f}",
            color="#e2e8f0", fontsize=11, fontweight="bold", pad=12
        )

        plt.savefig(output_path, facecolor="#131722", bbox_inches="tight", dpi=130)
        plt.close(fig)

    def list_screenshots(self, symbol: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List historical captures and their companion metadata."""
        items: List[Dict[str, Any]] = []
        if not self.base_dir.exists():
            return items

        json_files = list(self.base_dir.rglob("*.json"))
        json_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        for p in json_files[:limit]:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if symbol and data.get("symbol") != symbol:
                        continue
                    items.append(data)
            except Exception:
                continue

        return items

screenshot_service = ScreenshotService()
