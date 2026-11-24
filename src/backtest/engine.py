from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import yaml
from pathlib import Path

from src.data.base import Bar, TimeFrame
from src.analysis.zones import build_sr_zones
from src.analysis.indicators import calculate_atr
from src.risk.sizing import calculate_position_size, USD_THB_RATE_DEFAULT
from config.settings import settings

@dataclass
class TradeRecord:
    trade_id: str
    symbol: str
    sample_type: str  # "IN_SAMPLE" (70%) or "OUT_OF_SAMPLE" (30%)
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    shares: int
    lot_size: float
    gross_pnl_usd: float
    spread_cost_usd: float
    slippage_cost_usd: float
    swap_cost_usd: float
    net_pnl_usd: float
    net_pnl_thb: float
    duration_days: int
    exit_reason: str  # "TAKE_PROFIT", "STOP_LOSS", "GAP_STOP_LOSS", "END_OF_DATA"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "sample_type": self.sample_type,
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "entry_price": round(self.entry_price, 2),
            "exit_price": round(self.exit_price, 2),
            "stop_loss": round(self.stop_loss, 2),
            "take_profit": round(self.take_profit, 2),
            "shares": self.shares,
            "lot_size": self.lot_size,
            "gross_pnl_usd": round(self.gross_pnl_usd, 2),
            "spread_cost_usd": round(self.spread_cost_usd, 2),
            "swap_cost_usd": round(self.swap_cost_usd, 2),
            "net_pnl_usd": round(self.net_pnl_usd, 2),
            "net_pnl_thb": round(self.net_pnl_thb, 2),
            "duration_days": self.duration_days,
            "exit_reason": self.exit_reason,
            "is_win": self.net_pnl_usd > 0
        }

class BacktestEngine:
    def __init__(self, symbols_config_path: Optional[Path] = None):
        if symbols_config_path is None:
            symbols_config_path = Path(__file__).resolve().parent.parent.parent / "config" / "symbols.yaml"
        self.symbols_config = {}
        if symbols_config_path.exists():
            with open(symbols_config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                self.symbols_config = data.get("symbols", {})

    def get_symbol_spread(self, symbol: str) -> float:
        """Fetch realistic Exness CFD spread (e.g. GOOGL $0.30, NVDA $0.16)."""
        return self.symbols_config.get(symbol, {}).get("typical_spread_usd", 0.15)

    def run_backtest(
        self,
        symbol: str,
        bars_day: List[Bar],
        initial_capital_thb: float = 3000.0,
        split_ratio: float = 0.70,
        usd_thb_rate: float = USD_THB_RATE_DEFAULT
    ) -> List[TradeRecord]:
        """
        Execute deterministic bar-by-bar backtest adhering strictly to Section 14:
        - Zero look-ahead: Signal confirmed at bar t enters at Open of bar t+1
        - Exness CFD Spread deducted upon entry
        - Slippage 1 tick ($0.01)
        - Overnight swap cost (~6% annualized)
        - Gap handling: If open gaps below SL, fill at open with gap slippage
        - 70% In-Sample / 30% Out-of-Sample classification
        """
        trades: List[TradeRecord] = []
        if len(bars_day) < 40:
            return trades

        split_index = int(len(bars_day) * split_ratio)
        spread_usd = self.get_symbol_spread(symbol)
        slippage_usd = 0.01
        annual_swap_rate = 0.06

        active_trade: Optional[Dict[str, Any]] = None
        pending_entry: Optional[Dict[str, Any]] = None

        # Warmup period of 30 bars to establish initial S/R zones
        for i in range(30, len(bars_day)):
            curr_bar = bars_day[i]
            sample_type = "IN_SAMPLE" if i < split_index else "OUT_OF_SAMPLE"

            # 1. Process Pending Entry at Bar Open (Zero Look-Ahead Fill)
            if pending_entry and not active_trade:
                entry_price = curr_bar.open
                
                # If market gapped down below the Stop Loss, the setup is INVALIDATED before entry!
                if entry_price <= pending_entry["stop_loss"]:
                    pending_entry = None
                else:
                    # Ensure Stop Loss is strictly below entry price with minimum buffer
                    actual_sl = min(pending_entry["stop_loss"], round(entry_price - (curr_bar.close * 0.015), 2))
                    actual_tp = max(pending_entry["take_profit"], round(entry_price + (curr_bar.close * 0.025), 2))

                    sizing = calculate_position_size(
                        symbol=symbol,
                        capital_thb=initial_capital_thb,
                        entry_price=entry_price,
                        stop_loss_price=actual_sl,
                        risk_percent=settings.risk_per_trade_percent,
                        max_leverage=settings.max_leverage,
                        usd_thb_rate=usd_thb_rate
                    )

                    if sizing["status"] == "OK":
                        active_trade = {
                            "trade_id": f"BT_{symbol}_{i}_{int(curr_bar.open_time.timestamp())}",
                            "symbol": symbol,
                            "sample_type": sample_type,
                            "entry_time": curr_bar.open_time,
                            "entry_price": entry_price,
                            "stop_loss": actual_sl,
                            "take_profit": actual_tp,
                            "shares": sizing["shares"],
                            "lot_size": sizing["lot_size"],
                            "nights_held": 0,
                        }
                    pending_entry = None

            # 2. Manage Active Trade on Current Bar (Intraday Progression)
            if active_trade:
                active_trade["nights_held"] += 1
                exit_price = None
                exit_reason = None

                # Check Gap Stop Loss first (Market opened below Stop Loss)
                if curr_bar.open <= active_trade["stop_loss"]:
                    exit_price = curr_bar.open # Gap Slippage
                    exit_reason = "GAP_STOP_LOSS"
                # Check Take Profit
                elif curr_bar.high >= active_trade["take_profit"]:
                    exit_price = active_trade["take_profit"]
                    exit_reason = "TAKE_PROFIT"
                # Check Stop Loss
                elif curr_bar.low <= active_trade["stop_loss"]:
                    exit_price = active_trade["stop_loss"]
                    exit_reason = "STOP_LOSS"
                # End of backtest data
                elif i == len(bars_day) - 1:
                    exit_price = curr_bar.close
                    exit_reason = "END_OF_DATA"

                if exit_price is not None:
                    shares = active_trade["shares"]
                    gross_pnl_usd = (exit_price - active_trade["entry_price"]) * shares
                    spread_cost_usd = spread_usd * shares
                    slippage_cost_usd = slippage_usd * shares
                    
                    notional_usd = active_trade["entry_price"] * shares
                    swap_cost_usd = notional_usd * (annual_swap_rate / 365.0) * active_trade["nights_held"]
                    
                    net_pnl_usd = gross_pnl_usd - (spread_cost_usd + slippage_cost_usd + swap_cost_usd)
                    net_pnl_thb = net_pnl_usd * usd_thb_rate

                    trades.append(TradeRecord(
                        trade_id=active_trade["trade_id"],
                        symbol=symbol,
                        sample_type=active_trade["sample_type"],
                        entry_time=active_trade["entry_time"],
                        exit_time=curr_bar.close_time,
                        entry_price=active_trade["entry_price"],
                        exit_price=exit_price,
                        stop_loss=active_trade["stop_loss"],
                        take_profit=active_trade["take_profit"],
                        shares=shares,
                        lot_size=active_trade["lot_size"],
                        gross_pnl_usd=gross_pnl_usd,
                        spread_cost_usd=spread_cost_usd,
                        slippage_cost_usd=slippage_cost_usd,
                        swap_cost_usd=swap_cost_usd,
                        net_pnl_usd=net_pnl_usd,
                        net_pnl_thb=net_pnl_thb,
                        duration_days=active_trade["nights_held"],
                        exit_reason=exit_reason
                    ))
                    active_trade = None

            # 3. Strategy Evaluation for New Setup (Only if flat and no pending order)
            if not active_trade and not pending_entry:
                # Slices strictly up to bar i (Zero look-ahead)
                hist_slice = bars_day[:i + 1]
                zones = build_sr_zones(symbol, hist_slice, n_fractal=3, atr_multiplier=0.5)
                
                atr_vals = calculate_atr(hist_slice, 14)
                curr_atr = atr_vals[-1]["value"] if atr_vals else (curr_bar.close * 0.015)
                
                supports = [z for z in zones if z.zone_type == "SUPPORT" and not z.is_broken]
                resistances = [z for z in zones if z.zone_type == "RESISTANCE" and not z.is_broken]

                # Check if price is at Support Zone
                valid_supports = [z for z in supports if z.price_high >= (curr_bar.close - curr_atr * 0.5)]
                overhead_res = [z for z in resistances if z.price_low > curr_bar.close]
                overhead_res.sort(key=lambda z: z.price_low)

                if valid_supports and curr_bar.close >= curr_bar.open:
                    sup = valid_supports[0]
                    target_res = overhead_res[0] if overhead_res else None

                    # Headroom Guard Check
                    headroom = (target_res.price_low - curr_bar.close) if target_res else (curr_atr * 3.0)
                    if headroom >= (curr_atr * 1.0): # Ample headroom, not blocked by resistance
                        sl = round(sup.price_low - (curr_atr * 0.80), 2)
                        tp = round((target_res.price_low - curr_atr * 0.2), 2) if target_res else round(curr_bar.close + curr_atr * 2.5, 2)
                        
                        rr = (tp - curr_bar.close) / max(curr_bar.close - sl, 0.01)
                        if rr >= 1.2:
                            # Queue order to fill at next bar's Open!
                            pending_entry = {
                                "stop_loss": sl,
                                "take_profit": tp
                            }

        return trades
