from typing import List, Dict, Any
from src.backtest.engine import TradeRecord

class BacktestMetrics:
    @staticmethod
    def _compute_subset(trades: List[TradeRecord], initial_capital_thb: float) -> Dict[str, Any]:
        if not trades:
            return {
                "total_trades": 0,
                "win_trades": 0,
                "loss_trades": 0,
                "win_rate_percent": 0.0,
                "net_profit_thb": 0.0,
                "net_profit_usd": 0.0,
                "net_return_percent": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_percent": 0.0,
                "max_drawdown_thb": 0.0,
                "expectancy_thb": 0.0,
                "max_consecutive_losses": 0,
                "total_costs_thb": 0.0,
            }

        total_trades = len(trades)
        win_trades = [t for t in trades if t.net_pnl_thb > 0]
        loss_trades = [t for t in trades if t.net_pnl_thb <= 0]

        win_count = len(win_trades)
        loss_count = len(loss_trades)
        win_rate = (win_count / total_trades) * 100.0 if total_trades > 0 else 0.0

        gross_profit_thb = sum(t.net_pnl_thb for t in win_trades)
        gross_loss_thb = abs(sum(t.net_pnl_thb for t in loss_trades))
        net_profit_thb = sum(t.net_pnl_thb for t in trades)
        net_profit_usd = sum(t.net_pnl_usd for t in trades)
        net_return_percent = (net_profit_thb / initial_capital_thb) * 100.0

        profit_factor = round(gross_profit_thb / max(gross_loss_thb, 0.01), 2)
        if gross_loss_thb == 0 and gross_profit_thb > 0:
            profit_factor = 99.0

        avg_win_thb = (gross_profit_thb / win_count) if win_count > 0 else 0.0
        avg_loss_thb = (gross_loss_thb / loss_count) if loss_count > 0 else 0.0
        expectancy_thb = ((win_rate / 100.0) * avg_win_thb) - (((100.0 - win_rate) / 100.0) * avg_loss_thb)

        # Max Consecutive Losses
        max_consec_losses = 0
        current_losses = 0
        for t in trades:
            if t.net_pnl_thb <= 0:
                current_losses += 1
                max_consec_losses = max(max_consec_losses, current_losses)
            else:
                current_losses = 0

        # Drawdown calculation
        equity = initial_capital_thb
        peak = equity
        max_dd_thb = 0.0
        max_dd_pct = 0.0

        for t in trades:
            equity += t.net_pnl_thb
            if equity > peak:
                peak = equity
            dd = peak - equity
            dd_pct = (dd / peak) * 100.0 if peak > 0 else 0.0
            if dd > max_dd_thb:
                max_dd_thb = dd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        total_costs_thb = sum((t.spread_cost_usd + t.slippage_cost_usd + t.swap_cost_usd) * 35.0 for t in trades)

        return {
            "total_trades": total_trades,
            "win_trades": win_count,
            "loss_trades": loss_count,
            "win_rate_percent": round(win_rate, 1),
            "gross_profit_thb": round(gross_profit_thb, 2),
            "gross_loss_thb": round(gross_loss_thb, 2),
            "net_profit_thb": round(net_profit_thb, 2),
            "net_profit_usd": round(net_profit_usd, 2),
            "net_return_percent": round(net_return_percent, 2),
            "profit_factor": profit_factor,
            "max_drawdown_percent": round(max_dd_pct, 2),
            "max_drawdown_thb": round(max_dd_thb, 2),
            "expectancy_thb": round(expectancy_thb, 2),
            "max_consecutive_losses": max_consec_losses,
            "total_costs_thb": round(total_costs_thb, 2),
        }

    @staticmethod
    def calculate_full_report(
        trades: List[TradeRecord],
        initial_capital_thb: float = 3000.0
    ) -> Dict[str, Any]:
        """Generate comprehensive Backtest Report including In/Out-of-sample comparison."""
        trades.sort(key=lambda t: t.exit_time)

        in_sample_trades = [t for t in trades if t.sample_type == "IN_SAMPLE"]
        out_sample_trades = [t for t in trades if t.sample_type == "OUT_OF_SAMPLE"]

        overall_metrics = BacktestMetrics._compute_subset(trades, initial_capital_thb)
        in_sample_metrics = BacktestMetrics._compute_subset(in_sample_trades, initial_capital_thb)
        out_sample_metrics = BacktestMetrics._compute_subset(out_sample_trades, initial_capital_thb)

        # Build Equity Curve Points
        running_equity = initial_capital_thb
        equity_curve = [{
            "date": trades[0].entry_time.strftime("%Y-%m-%d") if trades else "Start",
            "equity_thb": round(initial_capital_thb, 2),
            "pnl": 0.0,
            "trade_id": "INIT"
        }]

        for t in trades:
            running_equity += t.net_pnl_thb
            equity_curve.append({
                "date": t.exit_time.strftime("%Y-%m-%d"),
                "equity_thb": round(running_equity, 2),
                "pnl": round(t.net_pnl_thb, 2),
                "symbol": t.symbol,
                "trade_id": t.trade_id,
                "sample_type": t.sample_type
            })

        # Breakdown by Symbol
        symbols = sorted(list(set(t.symbol for t in trades)))
        symbol_breakdown = {}
        for sym in symbols:
            sym_trades = [t for t in trades if t.symbol == sym]
            symbol_breakdown[sym] = BacktestMetrics._compute_subset(sym_trades, initial_capital_thb)

        return {
            "initial_capital_thb": initial_capital_thb,
            "final_equity_thb": round(running_equity, 2),
            "overall": overall_metrics,
            "in_sample": in_sample_metrics,
            "out_of_sample": out_sample_metrics,
            "equity_curve": equity_curve,
            "symbol_breakdown": symbol_breakdown,
            "trade_logs": [t.to_dict() for t in trades]
        }
