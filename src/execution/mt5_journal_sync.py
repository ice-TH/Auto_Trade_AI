"""
MT5 Journal Sync Engine
Synchronizes closed deals and orders from MetaTrader 5 into the Trading Journal Pro database.
Handles position pairing, exact risk calculation, currency conversion (USC/USD), and R-multiple determination.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

from src.storage.models import PortfolioModel, JournalTradeModel

logger = logging.getLogger("mt5_journal_sync")

def get_connected_mt5_account_info() -> Dict[str, Any]:
    """Retrieve connected MT5 account summary or disconnected state."""
    if not MT5_AVAILABLE:
        return {"connected": False, "error": "MetaTrader5 Python module not available"}
    
    if not mt5.initialize():
        return {"connected": False, "error": "MT5 terminal not running or not initialized"}
    
    acc = mt5.account_info()
    if not acc:
        mt5.shutdown()
        return {"connected": False, "error": "No account logged into MT5"}
    
    info = {
        "connected": True,
        "login": str(acc.login),
        "server": acc.server,
        "currency": acc.currency,
        "balance": acc.balance,
        "equity": acc.equity,
        "is_cent": (acc.currency.upper() == "USC"),
        "is_demo": "demo" in acc.server.lower() or "trial" in acc.server.lower()
    }
    mt5.shutdown()
    return info

def sync_mt5_deals_to_portfolio(
    portfolio_id: str,
    db: Session,
    days_back: int = 90
) -> Dict[str, Any]:
    """
    Fetches closed deals from MT5, pairs them with entry orders to compute
    exact risk, PnL, and R-multiple, then upserts them into JournalTradeModel.
    """
    if not MT5_AVAILABLE:
        return {"status": "ERROR", "message": "MetaTrader5 module is not installed"}

    if not mt5.initialize():
        return {"status": "ERROR", "message": "Failed to connect to MT5 terminal. Please ensure MT5 is open."}

    port = db.query(PortfolioModel).filter(PortfolioModel.id == portfolio_id).first()
    if not port:
        mt5.shutdown()
        return {"status": "ERROR", "message": f"Portfolio {portfolio_id} not found"}

    now = datetime.now()
    from_date = now - timedelta(days=days_back)
    deals = mt5.history_deals_get(from_date, now)
    acc = mt5.account_info()
    
    if acc is None:
        mt5.shutdown()
        return {"status": "ERROR", "message": "MT5 account authorization required"}

    is_cent = (acc.currency.upper() == "USC")
    acc_login_str = str(acc.login)

    # Optional: Update portfolio account_login if empty
    if not port.account_login or port.account_login == "Default":
        port.account_login = acc_login_str
        db.commit()

    # Auto-align portfolio capital & currency based on MT5 account
    deposit_deals = [d for d in deals if d.type == 2 or (not d.symbol and d.profit > 0)]
    total_deposits = sum(float(d.profit) for d in deposit_deals)

    # Adopt account currency if not explicitly customized
    if not port.currency or port.currency in ["USD", "USC"]:
        port.currency = "USC" if is_cent else acc.currency

    # Update initial capital to match actual MT5 deposit or balance
    if total_deposits > 0:
        if port.currency == "USC":
            port.initial_capital = round(total_deposits if is_cent else total_deposits * 100.0, 2)
        elif port.currency == "THB":
            port.initial_capital = round((total_deposits / 100.0 if is_cent else total_deposits) * 35.0, 2)
        else: # USD
            port.initial_capital = round(total_deposits / 100.0 if is_cent else total_deposits, 2)
    elif float(acc.balance) > 0 and (port.initial_capital == 1000.0 or port.initial_capital <= 0):
        if port.currency == "USC":
            port.initial_capital = round(float(acc.balance), 2)
        elif port.currency == "THB":
            port.initial_capital = round((float(acc.balance) / 100.0 if is_cent else float(acc.balance)) * 35.0, 2)
        else: # USD
            port.initial_capital = round(float(acc.balance) / 100.0 if is_cent else float(acc.balance), 2)
    db.commit()

    if not deals:
        mt5.shutdown()
        return {"status": "SUCCESS", "synced_count": 0, "message": "No deals found in specified range"}

    # Filter closing deals: entry == 1 (DEAL_ENTRY_OUT) and has symbol
    closing_deals = [d for d in deals if d.symbol and d.entry == 1]

    synced_count = 0
    updated_count = 0

    for deal in closing_deals:
        pos_id = deal.position_id
        
        # Find entry deal for this position
        entry_deal = None
        for d in deals:
            if d.position_id == pos_id and d.entry == 0:
                entry_deal = d
                break

        # Query original order to retrieve SL, TP, and comment
        order_sl = 0.0
        order_tp = 0.0
        order_comment = ""
        order_type = 0 # 0=Buy, 1=Sell
        
        hist_orders = mt5.history_orders_get(ticket=pos_id)
        if hist_orders and len(hist_orders) > 0:
            ord_obj = hist_orders[0]
            order_sl = float(ord_obj.sl or 0.0)
            order_tp = float(ord_obj.tp or 0.0)
            order_comment = str(ord_obj.comment or "")
            order_type = int(ord_obj.type)
        elif entry_deal:
            order_type = int(entry_deal.type)

        direction = "BUY" if order_type == 0 else "SELL"
        entry_price = float(entry_deal.price) if entry_deal else float(deal.price)
        close_price = float(deal.price)

        # Net Profit in account currency (including swap & commission)
        raw_profit = float(deal.profit) + float(deal.swap) + float(deal.commission)
        if port.currency == "USC":
            profit_conv = round(raw_profit if is_cent else raw_profit * 100.0, 2)
        elif port.currency == "THB":
            profit_conv = round((raw_profit / 100.0 if is_cent else raw_profit) * 35.0, 2)
        else: # USD
            profit_conv = round(raw_profit / 100.0 if is_cent else raw_profit, 2)

        # Calculate exact monetary Risk
        risk_conv = 0.0
        if order_sl > 0 and entry_price > 0:
            calc_action = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
            calc_loss = mt5.order_calc_profit(calc_action, deal.symbol, deal.volume, entry_price, order_sl)
            if calc_loss is not None:
                calc_risk = abs(float(calc_loss))
                if calc_risk > 0:
                    if port.currency == "USC":
                        risk_conv = round(calc_risk if is_cent else calc_risk * 100.0, 2)
                    elif port.currency == "THB":
                        risk_conv = round((calc_risk / 100.0 if is_cent else calc_risk) * 35.0, 2)
                    else: # USD
                        risk_conv = round(calc_risk / 100.0 if is_cent else calc_risk, 2)

        # Fallback risk if SL was not set
        if risk_conv <= 0:
            risk_conv = round(port.initial_capital * (port.risk_per_trade_percent / 100.0), 2)
        if risk_conv <= 0:
            risk_conv = 10.0

        r_multiple = round(profit_conv / risk_conv, 2) if risk_conv > 0 else 0.0
        outcome = "W" if r_multiple > 0.05 else ("L" if r_multiple < -0.05 else "BE")

        # Determine Setup name from comment or default
        combined_comm = f"{order_comment} {deal.comment or ''}".strip()
        setup = "MT5 Execution"
        if "antigravity" in combined_comm.lower():
            setup = "Antigravity AI (MT5)"
        elif "fibo" in combined_comm.lower():
            setup = "Fibo Confluence (MT5)"
        elif "scalp" in combined_comm.lower():
            setup = "Scalping Setup (MT5)"
        elif order_comment:
            setup = f"{order_comment.strip()} (MT5)"

        close_dt = datetime.fromtimestamp(deal.time, tz=timezone.utc)
        clean_symbol = deal.symbol.rstrip('c').rstrip('m').rstrip('.')

        # Check if trade already recorded
        existing_trade = db.query(JournalTradeModel).filter(
            JournalTradeModel.portfolio_id == portfolio_id,
            JournalTradeModel.mt5_ticket == deal.ticket
        ).first()

        if existing_trade:
            # Update values
            existing_trade.total_pnl = profit_conv
            existing_trade.risk_usd = risk_conv
            existing_trade.r_multiple = r_multiple
            existing_trade.outcome = outcome
            existing_trade.close_price = close_price
            existing_trade.comment = f"Exit: {deal.comment or 'Closed'} | SL: {order_sl} | TP: {order_tp}"
            updated_count += 1
        else:
            # Insert new trade record
            count_total = db.query(JournalTradeModel).filter(JournalTradeModel.portfolio_id == portfolio_id).count()
            new_trade = JournalTradeModel(
                portfolio_id=portfolio_id,
                trade_no=count_total + 1,
                trade_date=close_dt,
                symbol=clean_symbol,
                direction=direction,
                risk_usd=risk_conv,
                total_pnl=profit_conv,
                r_multiple=r_multiple,
                setup=setup,
                outcome=outcome,
                comment=f"Exit: {deal.comment or 'Closed'} | SL: {order_sl} | TP: {order_tp}",
                mt5_ticket=deal.ticket
            )
            db.add(new_trade)
            synced_count += 1

    db.commit()
    mt5.shutdown()

    return {
        "status": "SUCCESS",
        "account_login": acc_login_str,
        "is_cent": is_cent,
        "synced_count": synced_count,
        "updated_count": updated_count,
        "total_closing_deals": len(closing_deals),
        "message": f"ซิงก์ข้อมูลจาก MT5 สำเร็จ: เพิ่มใหม่ {synced_count} ไม้, อัปเดต {updated_count} ไม้"
    }
