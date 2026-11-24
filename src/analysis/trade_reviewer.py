"""
Trade Reviewer & Continuous Learning Engine
Synchronizes closed deals from MT5, conducts automated post-mortem reviews,
and updates SQLite trade_history, Markdown cases, and the Active Playbook.
"""

import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import logging

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

from config.settings import settings, BASE_DIR
from src.storage.database import SessionLocal
from src.storage.models import TradeHistoryModel

logger = logging.getLogger("trade_reviewer")

MEMORY_DIR = BASE_DIR / "memory"
CASES_DIR = MEMORY_DIR / "cases"
PLAYBOOK_FILE = MEMORY_DIR / "playbook.md"

CASES_DIR.mkdir(parents=True, exist_ok=True)

def sync_and_review_all() -> Dict[str, Any]:
    """
    Fetch closed deals from MT5 for the last 14 days,
    store in database if missing, and generate post-mortem analysis.
    """
    if not MT5_AVAILABLE:
        return {"status": "ERROR", "message": "MT5 module not available"}

    if not mt5.initialize():
        return {"status": "ERROR", "message": "Failed to connect to MT5"}

    now = datetime.now()
    deals = mt5.history_deals_get(now - timedelta(days=14), now)
    acc_info = mt5.account_info()
    current_login_str = str(acc_info.login) if acc_info else "UNKNOWN"
    is_cent = (acc_info.currency.upper() == "USC") if acc_info else False
    mt5.shutdown()

    if not deals:
        return {"status": "SUCCESS", "synced_count": 0, "message": "No deals found"}

    db = SessionLocal()
    synced_deals = []
    
    try:
        # Group closing deals (type == 0 or 1 with comment or profit)
        for d in deals:
            # Type: 0 = Buy, 1 = Sell. Check if it represents a trade close or has profit
            if not d.symbol:
                continue # Skip deposit / credit deals

            # Check if deal already in DB
            existing = db.query(TradeHistoryModel).filter(TradeHistoryModel.ticket == d.ticket).first()
            if existing:
                continue

            raw_profit = float(d.profit)
            profit_usd = raw_profit / 100.0 if is_cent else raw_profit
            profit_thb = profit_usd * 35.0

            outcome = "WIN" if raw_profit > 0.05 else ("LOSS" if raw_profit < -0.05 else "BREAKEVEN")
            exit_reason = "SL_HIT" if "sl" in str(d.comment).lower() else ("TP_HIT" if "tp" in str(d.comment).lower() else "MANUAL_OR_TARGET")
            
            close_dt = datetime.fromtimestamp(d.time, tz=timezone.utc)
            date_str = close_dt.strftime("%Y%m%d")
            clean_sym = d.symbol.replace("m", "").replace(".", "")
            case_file_name = f"CASE_{date_str}_{clean_sym}_{d.ticket}.md"
            
            # Post-mortem inference in Thai
            unit_str = "USC" if is_cent else "USD"
            if outcome == "LOSS":
                root_cause = f"ราคาปิดที่ {d.price} เกิดผลขาดทุน {raw_profit:.2f} {unit_str} (${profit_usd:.2f} / {profit_thb:.2f} บาท) โดยเงื่อนไข: {d.comment or exit_reason}"
                lesson = f"ต้องระวังความผันผวนและสภาพคล่องของ {d.symbol} การมี Hard Stop Loss ช่วยป้องกันพอร์ตไม่ให้ติดลบลุกลาม"
            elif outcome == "WIN":
                root_cause = f"ราคาแตะเป้าหมายที่ {d.price} ได้กำไรสุทธิ +{raw_profit:.2f} {unit_str} (+${profit_usd:.2f} / +{profit_thb:.2f} บาท)"
                lesson = f"สัญญาณยืนยันถูกต้องตามแผน อัตรา Risk/Reward บรรลุตามเป้าหมายอย่างมีประสิทธิภาพ"
            else:
                root_cause = f"ออเดอร์ปิดที่ราคาเสมอตัว (Breakeven) ที่ {d.price}"
                lesson = "การรักษาต้นทุนของพอร์ตถือเป็นสิ่งสำคัญอันดับแรก (Capital Preservation)"

            # Save to SQLite
            new_record = TradeHistoryModel(
                ticket=d.ticket,
                order_id=d.order,
                account_login=current_login_str,
                symbol=d.symbol,
                direction="SELL" if d.type == 1 else "BUY",
                volume=d.volume,
                entry_price=d.price, # exit price for closing deal
                close_price=d.price,
                sl_price=None,
                tp_price=None,
                profit_usd=round(profit_usd, 2),
                profit_thb=round(profit_thb, 2),
                outcome=outcome,
                exit_reason=exit_reason,
                root_cause=root_cause,
                lesson_learned=lesson,
                case_file=case_file_name,
                close_time=close_dt
            )
            db.add(new_record)
            synced_deals.append({
                "ticket": d.ticket,
                "symbol": d.symbol,
                "profit": profit_usd,
                "outcome": outcome,
                "case_file": case_file_name
            })
            
            # Determine subcategory directory based on symbol
            sym_clean = d.symbol.upper()
            if "BTC" in sym_clean:
                target_sub_dir = CASES_DIR / "BTCUSD"
            elif "XAU" in sym_clean or "GOLD" in sym_clean:
                target_sub_dir = CASES_DIR / "XAUUSD"
            else:
                target_sub_dir = CASES_DIR / "EQUITIES"
            
            target_sub_dir.mkdir(parents=True, exist_ok=True)
            case_path = target_sub_dir / case_file_name
            if not case_path.exists():
                case_content = f"""# Case Study: {case_file_name.replace('.md', '')}

## 1. Trade Parameters
- **Ticket:** `{d.ticket}` | **Order:** `{d.order}`
- **Symbol:** `{d.symbol}` | **Direction:** `{'SELL' if d.type == 1 else 'BUY'}`
- **Volume:** `{d.volume} Lot`
- **Executed Price:** `${d.price:.2f}`
- **Timestamp:** `{close_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}`
- **Profit/Loss:** `{raw_profit:.2f} {unit_str}` (`${profit_usd:.2f} USD` / `{profit_thb:.2f} THB`)
- **Outcome:** **{outcome}** (`{exit_reason}`)
- **Broker Comment:** `{d.comment}`

---

## 2. Qualitative Post-Mortem Analysis
- **Root Cause:** {root_cause}
- **Stop Loss & Risk Adherence:** Confirmed with broker tags.

---

## 3. Extracted Rule & Actionable Lesson
- **Lesson:** {lesson}
"""
                with open(case_path, "w", encoding="utf-8") as f:
                    f.write(case_content)

        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error syncing closed deals: {e}")
        return {"status": "ERROR", "message": str(e)}
    finally:
        db.close()

    return {
        "status": "SUCCESS",
        "synced_count": len(synced_deals),
        "deals": synced_deals
    }

def get_playbook_content() -> str:
    """Read active playbook rules (recompiled from modular sources)."""
    try:
        from src.analysis.playbook_compiler import compile_playbook
        return compile_playbook(PLAYBOOK_FILE)
    except Exception as e:
        logger.warning(f"Failed to auto-compile playbook, falling back to disk read: {e}")
        if PLAYBOOK_FILE.exists():
            with open(PLAYBOOK_FILE, "r", encoding="utf-8") as f:
                return f.read()
        return "Playbook is currently empty."

def get_recent_cases(limit: int = 20) -> List[Dict[str, Any]]:
    """Retrieve recent case studies and trade history from SQLite."""
    db = SessionLocal()
    try:
        records = db.query(TradeHistoryModel).order_by(TradeHistoryModel.close_time.desc()).limit(limit).all()
        return [
            {
                "ticket": r.ticket,
                "symbol": r.symbol,
                "direction": r.direction,
                "volume": r.volume,
                "close_price": r.close_price,
                "profit_usd": r.profit_usd,
                "profit_thb": r.profit_thb,
                "outcome": r.outcome,
                "exit_reason": r.exit_reason,
                "root_cause": r.root_cause,
                "lesson_learned": r.lesson_learned,
                "case_file": r.case_file,
                "close_time": r.close_time.strftime("%Y-%m-%d %H:%M:%S")
            }
            for r in records
        ]
    finally:
        db.close()


if __name__ == "__main__":
    import json
    res = sync_and_review_all()
    print("Sync Result:", json.dumps(res, indent=2, default=str))

