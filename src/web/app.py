from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Depends, HTTPException, Query, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config.settings import settings
from src.data.base import TimeFrame, DataStatus
from src.data.mock_adapter import MockDataAdapter
from src.data.mt5_adapter import MT5DataAdapter
from src.data.calendar_guard import TZ_UTC, TZ_BANGKOK, to_bangkok, to_eastern, get_market_session
from src.analysis.indicators import calculate_ema, calculate_atr, calculate_volume_ma
from src.analysis.zones import build_sr_zones
from src.analysis.swings import detect_swings
from src.analysis.auxiliary import calculate_fibonacci_levels, detect_demand_supply_zones
from src.storage.database import init_db, get_db
from src.storage.models import ManualZoneModel, PlanModel, AuditLogModel, PortfolioModel, JournalTradeModel
from src.capture.screenshot_service import screenshot_service
from src.strategy.plans import TradingPlan, PlanStatus
from src.strategy.rules import evaluate_bounce_setup
from src.analysis.ai_analyzer import analyze_market_narrative, generate_antigravity_prompt_context
from src.backtest.engine import BacktestEngine, TradeRecord
from src.backtest.metrics import BacktestMetrics
from src.execution.mt5_client import mt5_client
from src.execution.reconciliation import order_reconciler
from src.execution.mt5_journal_sync import (
    sync_mt5_deals_to_portfolio,
    get_connected_mt5_account_info,
    ensure_portfolio_for_mt5_account,
)

# Cache evaluated plans & backtest results
cached_plans: Dict[str, TradingPlan] = {}
non_entry_journal: List[Dict[str, Any]] = []
cached_backtest_report: Optional[Dict[str, Any]] = None
backtest_engine = BacktestEngine()
auto_execution_enabled: bool = True

# Initialize Database tables
init_db()

# Initialize Market Data Adapters
mock_adapter = MockDataAdapter()
mt5_adapter = MT5DataAdapter()
# Default to MT5 Live Feed automatically if MT5 is available, fallback to MOCK
active_adapter_type = "MT5" if mt5_adapter._ensure_connected() else "MOCK"
data_adapter = mt5_adapter if active_adapter_type == "MT5" else mock_adapter

app = FastAPI(
    title="AutoTrade - US Equities Analysis & MT5 CFD System",
    description="Deterministic quantitative analysis & risk management dashboard running locally.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Mount screenshots directory for journal & gallery viewing
app.mount("/screenshots-view", StaticFiles(directory=str(settings.screenshots_dir)), name="screenshots-view")

@app.get("/")
def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "AutoTrade Backend running. Dashboard UI loading..."}

# ----------------- SYSTEM & HEALTH ENDPOINTS -----------------
@app.get("/api/status")
def get_system_status():
    now_utc = datetime.now(TZ_UTC)
    now_et = to_eastern(now_utc)
    now_bkk = to_bangkok(now_utc)
    market_session = get_market_session(now_utc)
    
    # Determine live balance from MT5 if connected, else fallback to settings
    live_balance_thb = settings.base_capital_thb
    mt5_client.connect()
    if mt5_client.is_connected and mt5_client.account_info:
        acc_bal = mt5_client.account_info.get("balance", 0.0)
        curr = mt5_client.account_info.get("currency", "USD")
        if acc_bal > 0:
            if curr == "USC":
                # In Cent account, 100 USC = 1 USD -> (acc_bal / 100) * 35.0 THB
                live_balance_thb = round((acc_bal / 100.0) * 35.0, 2)
            else:
                live_balance_thb = round(acc_bal * 35.0, 2)

    return {
        "status": "HEALTHY",
        "app_env": settings.app_env,
        "trading_mode": settings.trading_mode, # READ_ONLY by default
        "execution_enabled": settings.execution_enabled, # False
        "data_source": settings.data_source,
        "adapter_status": data_adapter.get_status(),
        "time": {
            "utc": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "eastern": now_et.strftime("%Y-%m-%d %H:%M:%S EDT/EST"),
            "bangkok": now_bkk.strftime("%Y-%m-%d %H:%M:%S +07"),
        },
        "market_session": market_session.value,
        "risk_profile": {
            "base_capital_thb": live_balance_thb,
            "max_leverage": settings.max_leverage, # Cap at 1:5
            "risk_per_trade_percent": settings.risk_per_trade_percent,
            "max_daily_loss_percent": settings.max_daily_loss_percent,
            "allow_overnight": settings.allow_overnight,
            "allow_weekend": settings.allow_weekend,
        },
        "mt5": {
            "installed_path": settings.mt5_path,
            "status": "DISCONNECTED (Read-Only Mode)",
            "message": "Execution bridge disabled in Phase 2. Demo connection planned for Phase 5."
        }
    }

@app.get("/api/symbols")
def get_symbols():
    # If active adapter is MT5, symbols_config might need to fallback to mock_adapter symbols list
    sym_cfg = getattr(data_adapter, "symbols_config", mock_adapter.symbols_config)
    return {
        "symbols": sym_cfg,
        "selected_alphabet": "GOOGL (Alphabet Inc. Class A)"
    }

# ----------------- DATA SOURCE SELECTION -----------------
class SwitchSourceReq(BaseModel):
    source: str # "MT5" or "MOCK"

@app.get("/api/data-source")
def get_data_source_status():
    global active_adapter_type, data_adapter
    if active_adapter_type == "MT5":
        mt5_client.connect()
    connected = mt5_client.is_connected
    acc = mt5_client.account_info if connected else {}
    server_str = acc.get("server", "").lower()
    is_demo = acc.get("is_demo", True)
    if "real" in server_str or acc.get("trade_mode") == 2 or acc.get("currency") == "USC":
        is_demo = False

    return {
        "active_source": active_adapter_type,
        "adapter_name": data_adapter.__class__.__name__,
        "mt5_connected": connected,
        "account_login": acc.get("login"),
        "account_server": acc.get("server"),
        "account_currency": acc.get("currency", "USD"),
        "account_type": "REAL (Cent)" if acc.get("currency") == "USC" else ("DEMO" if is_demo else "REAL"),
        "is_demo": is_demo,
        "available_sources": ["MOCK", "MT5"]
    }

@app.post("/api/data-source/switch")
def switch_data_source(req: SwitchSourceReq):
    global active_adapter_type, data_adapter
    target = req.source.upper()
    if target == "MT5":
        if not mt5_client.is_connected:
            conn_res = mt5_client.connect()
            if not conn_res.get("connected"):
                return {
                    "success": False,
                    "error": f"Failed to switch to MT5: {conn_res.get('error')}",
                    "active_source": active_adapter_type
                }
        active_adapter_type = "MT5"
        data_adapter = mt5_adapter
        # Clear plan cache to re-evaluate on real data
        cached_plans.clear()
        return {
            "success": True,
            "message": "Switched to Exness MT5 Live Data Source",
            "active_source": "MT5",
            "account_login": mt5_client.account_info.get("login")
        }
    elif target == "MOCK":
        active_adapter_type = "MOCK"
        data_adapter = mock_adapter
        cached_plans.clear()
        return {
            "success": True,
            "message": "Switched to Simulation (Mock Data) Source",
            "active_source": "MOCK"
        }
    else:
        raise HTTPException(status_code=400, detail="Invalid source. Choose 'MT5' or 'MOCK'.")

# ----------------- MARKET DATA & INDICATORS -----------------
@app.get("/api/market/quote/{symbol}")
def get_quote(symbol: str):
    symbol = symbol.upper()
    return data_adapter.get_latest_quote(symbol)

@app.get("/api/market/bars/{symbol}")
def get_bars(
    symbol: str,
    timeframe: str = Query(default="1D", pattern="^(1W|1D|15m|5m|1m)$"),
    limit: int = Query(default=350, ge=1, le=1000)
):
    symbol = symbol.upper()
    tf = TimeFrame(timeframe)
    bars = data_adapter.get_bars(symbol, tf, limit=limit)
    
    # Calculate indicators on the fly
    ema15 = calculate_ema(bars, 15)
    ema50 = calculate_ema(bars, 50)
    ema100 = calculate_ema(bars, 100)
    ema200 = calculate_ema(bars, 200)
    atr14 = calculate_atr(bars, 14)
    vol_ma = calculate_volume_ma(bars, 20)

    return {
        "symbol": symbol,
        "timeframe": tf.value,
        "count": len(bars),
        "status": DataStatus.SIMULATION.value,
        "bars": [b.to_dict() for b in bars],
        "indicators": {
            "ema15": ema15,
            "ema50": ema50,
            "ema100": ema100,
            "ema200": ema200,
            "atr14": atr14,
            "vol_ma20": vol_ma,
        }
    }

# ----------------- ZONES & ANALYSIS -----------------
@app.get("/api/zones/{symbol}")
def get_zones(symbol: str, db: Session = Depends(get_db)):
    symbol = symbol.upper()
    # Get DAY bars for core S/R (500 bars ~ 2 years for deep historical levels)
    day_bars = data_adapter.get_bars(symbol, TimeFrame.DAY, limit=500)
    auto_zones = build_sr_zones(symbol, day_bars, n_fractal=3, atr_multiplier=0.5)

    # Get M15 bars for intraday S/R (200 bars ~ 2 days, n_fractal=4 to filter chop)
    m15_bars = data_adapter.get_bars(symbol, TimeFrame.M15, limit=200)
    m15_zones = build_sr_zones(symbol, m15_bars, n_fractal=4, atr_multiplier=0.4)
    
    # Get manual zones from DB
    manual_records = db.query(ManualZoneModel).filter(ManualZoneModel.symbol == symbol).all()
    manual_zones = [{
        "zone_id": m.id,
        "symbol": m.symbol,
        "timeframe": m.timeframe,
        "zone_type": m.zone_type,
        "price_high": m.price_high,
        "price_low": m.price_low,
        "price_mid": (m.price_high + m.price_low) / 2.0,
        "label": m.label,
        "is_locked": m.is_locked,
        "source": "MANUAL",
        "author": m.author,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    } for m in manual_records]

    # Auxiliary: Fibonacci & Demand/Supply
    swings = detect_swings(day_bars, n=3)
    fib_data = calculate_fibonacci_levels(symbol, day_bars, swings)
    ds_zones = detect_demand_supply_zones(day_bars)

    return {
        "symbol": symbol,
        "auto_sr_zones": [z.to_dict() for z in auto_zones],
        "m15_sr_zones": [z.to_dict() for z in m15_zones],
        "manual_zones": manual_zones,
        "fibonacci": fib_data,
        "demand_supply": ds_zones,
    }

class ManualZoneCreate(BaseModel):
    symbol: str
    timeframe: str = "1D"
    price_high: float
    price_low: float
    label: str = "Manual Zone"
    zone_type: str = "SUPPORT"
    is_locked: bool = False

@app.post("/api/zones/manual")
def create_manual_zone(payload: ManualZoneCreate, db: Session = Depends(get_db)):
    zone_id = f"MAN_{payload.symbol}_{int(payload.price_low*100)}_{int(datetime.now().timestamp())}"
    zone = ManualZoneModel(
        id=zone_id,
        symbol=payload.symbol.upper(),
        timeframe=payload.timeframe,
        price_high=max(payload.price_high, payload.price_low),
        price_low=min(payload.price_high, payload.price_low),
        label=payload.label,
        zone_type=payload.zone_type,
        is_locked=payload.is_locked,
        author="User"
    )
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return {"status": "SUCCESS", "zone_id": zone.id}

@app.delete("/api/zones/manual/{zone_id}")
def delete_manual_zone(zone_id: str, db: Session = Depends(get_db)):
    zone = db.query(ManualZoneModel).filter(ManualZoneModel.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    if zone.is_locked:
        raise HTTPException(status_code=400, detail="Cannot delete a locked zone. Unlock it first.")
    db.delete(zone)
    db.commit()
    return {"status": "DELETED", "zone_id": zone_id}

@app.patch("/api/zones/manual/{zone_id}/lock")
def toggle_zone_lock(zone_id: str, db: Session = Depends(get_db)):
    zone = db.query(ManualZoneModel).filter(ManualZoneModel.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    zone.is_locked = not zone.is_locked
    db.commit()
    return {"status": "UPDATED", "zone_id": zone_id, "is_locked": zone.is_locked}

# ----------------- PLANS & STRATEGY ENGINE -----------------
@app.get("/api/plans/{symbol}")
def get_symbol_plan(symbol: str):
    symbol = symbol.upper()
    bars_w = data_adapter.get_bars(symbol, TimeFrame.WEEK, limit=150)
    bars_d = data_adapter.get_bars(symbol, TimeFrame.DAY, limit=500)
    bars_m = data_adapter.get_bars(symbol, TimeFrame.M15, limit=50)
    zones = build_sr_zones(symbol, bars_d, n_fractal=3)
    
    plan = evaluate_bounce_setup(
        symbol=symbol,
        bars_week=bars_w,
        bars_day=bars_d,
        bars_m15=bars_m,
        zones_day=zones,
        settings=settings
    )
    cached_plans[symbol] = plan
    
    # If rejected, record to journal
    if plan.status == PlanStatus.REJECTED_NO_TRADE:
        existing = next((item for item in non_entry_journal if item["symbol"] == symbol), None)
        journal_entry = {
            "symbol": symbol,
            "timestamp": datetime.now(TZ_UTC).isoformat(),
            "status": plan.status.value,
            "reason": plan.rejection_reason,
            "headroom": plan.headroom_to_resistance,
            "entry_price": plan.entry_price
        }
        if existing:
            non_entry_journal.remove(existing)
        non_entry_journal.insert(0, journal_entry)

    return plan.to_dict()

@app.post("/api/plans/evaluate")
def evaluate_all_symbols():
    sym_cfg = getattr(data_adapter, "symbols_config", mock_adapter.symbols_config)
    symbols = list(sym_cfg.keys())
    results = {}
    current_login = str(mt5_client.account_info.get("login", "")) if mt5_client.is_connected else "MOCK_SIM"
    for sym in symbols:
        bars_w = data_adapter.get_bars(sym, TimeFrame.WEEK, limit=150)
        bars_d = data_adapter.get_bars(sym, TimeFrame.DAY, limit=500)
        bars_m = data_adapter.get_bars(sym, TimeFrame.M15, limit=50)
        zones = build_sr_zones(sym, bars_d, n_fractal=3)
        plan = evaluate_bounce_setup(sym, bars_w, bars_d, bars_m, zones, settings)
        cached_plans[sym] = plan
        plan_dict = plan.to_dict()
        plan_dict["account_login"] = current_login
        results[sym] = plan_dict

        if plan.status == PlanStatus.REJECTED_NO_TRADE:
            existing = next((item for item in non_entry_journal if item["symbol"] == sym), None)
            entry = {
                "symbol": sym,
                "account_login": current_login,
                "timestamp": datetime.now(TZ_UTC).isoformat(),
                "status": plan.status.value,
                "reason": plan.rejection_reason,
                "headroom": plan.headroom_to_resistance,
                "entry_price": plan.entry_price
            }
            if existing:
                non_entry_journal.remove(existing)
            non_entry_journal.insert(0, entry)

    return {"status": "EVALUATED", "plans": results, "journal": non_entry_journal[:20]}

@app.get("/api/plans/journal/list")
def get_non_entry_journal():
    return {"journal": non_entry_journal[:30]}

# ----------------- EXPERIMENTAL BTC 1M SCALPER (MODULAR) -----------------
@app.get("/api/crypto/btc-1m")
def get_btc_1m_scalp_analysis():
    """
    Experimental 1m Fast Scalper for BTCUSD (Demand/Supply, S/R lines, Ascending Trendline).
    Modular and isolated: Does not affect the 7 US Equities.
    """
    try:
        from src.analysis.btc_scalper import scan_btc_1m
        return scan_btc_1m()
    except ImportError:
        raise HTTPException(status_code=404, detail="BTC Scalper module is disabled or removed.")

# ----------------- EXPERIMENTAL XAU/USD GOLD STRATEGY (MODULAR) -----------------
@app.get("/api/gold/analysis")
def get_gold_analysis():
    """
    Experimental XAU/USD Gold Strategy space.
    Modular and isolated: Does not affect BTC or the 7 US Equities.
    """
    try:
        from src.analysis.gold_strategy import scan_gold_setup
        return scan_gold_setup()
    except ImportError:
        raise HTTPException(status_code=404, detail="Gold Strategy module is disabled or removed.")

# ----------------- AI MEMORY & CONTINUOUS LEARNING -----------------
@app.get("/api/memory/playbook")
def get_playbook():
    """Retrieve active AI Playbook rules."""
    from src.analysis.trade_reviewer import get_playbook_content
    return {"content": get_playbook_content()}

@app.get("/api/memory/cases")
def get_cases(limit: int = Query(20, ge=1, le=100), account_login: Optional[str] = Query(default=None)):
    """Retrieve closed cases and post-mortem lessons, optionally isolated by MT5 account."""
    from src.analysis.trade_reviewer import get_recent_cases
    return {"cases": get_recent_cases(limit=limit, account_login=account_login)}

@app.post("/api/memory/sync")
def trigger_memory_sync():
    """Sync latest closed deals from MT5 and generate case studies."""
    from src.analysis.trade_reviewer import sync_and_review_all
    return sync_and_review_all()

# ----------------- AI NARRATIVE & ANTIGRAVITY -----------------
@app.get("/api/ai/narrative/{symbol}")
def get_ai_narrative(symbol: str):
    symbol = symbol.upper()
    bars_w = data_adapter.get_bars(symbol, TimeFrame.WEEK, limit=150)
    bars_d = data_adapter.get_bars(symbol, TimeFrame.DAY, limit=500)
    zones = build_sr_zones(symbol, bars_d, n_fractal=3)
    plan = cached_plans.get(symbol) or evaluate_bounce_setup(symbol, bars_w, bars_d, [], zones, settings)
    
    narrative = analyze_market_narrative(symbol, bars_w, bars_d, zones, plan)
    context_text = generate_antigravity_prompt_context(symbol, bars_d, zones, plan)
    
    return {
        "narrative": narrative,
        "antigravity_context": context_text
    }


AI_CHART_SETUPS_PATH = Path(__file__).resolve().parent.parent.parent / "data_store" / "ai_chart_setups.json"


def _load_ai_chart_setups() -> Dict[str, Any]:
    if not AI_CHART_SETUPS_PATH.exists():
        return {}
    try:
        return json.loads(AI_CHART_SETUPS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_ai_chart_setups(data: Dict[str, Any]) -> None:
    AI_CHART_SETUPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    AI_CHART_SETUPS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class AIChartSetupCreate(BaseModel):
    symbol: str
    direction: str = "WAIT"  # BUY, SELL, WAIT, NEUTRAL
    status: str = "WAITING_ZONE"
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    zone_low: Optional[float] = None
    zone_high: Optional[float] = None
    title: str = ""
    reason: str = ""
    timeframe: str = "5m"
    source: str = "AI_TRADER"


@app.post("/api/ai/chart-setup")
def save_ai_chart_setup(req: AIChartSetupCreate):
    """Save or update an AI Trader waiting zone & TP/SL setup for chart visualization."""
    sym = req.symbol.upper().strip()
    setups = _load_ai_chart_setups()
    setup_dict = req.model_dump()
    setup_dict["symbol"] = sym
    setup_dict["direction"] = req.direction.upper().strip()
    setup_dict["updated_at"] = datetime.now(TZ_UTC).isoformat()
    if setup_dict.get("entry_price") and setup_dict.get("stop_loss") and setup_dict.get("take_profit"):
        risk = abs(setup_dict["entry_price"] - setup_dict["stop_loss"])
        reward = abs(setup_dict["take_profit"] - setup_dict["entry_price"])
        setup_dict["rr_ratio"] = round(reward / risk, 2) if risk > 0 else 0.0
    else:
        setup_dict["rr_ratio"] = 0.0

    setups[sym] = setup_dict
    _save_ai_chart_setups(setups)
    return {"status": "SAVED", "setup": setup_dict}


@app.delete("/api/ai/chart-setup/{symbol}")
def delete_ai_chart_setup(symbol: str):
    """Clear custom AI Trader chart setup for a symbol."""
    sym = symbol.upper().strip()
    setups = _load_ai_chart_setups()
    removed = setups.pop(sym, None)
    _save_ai_chart_setups(setups)
    return {"status": "DELETED" if removed else "NOT_FOUND", "symbol": sym}


@app.get("/api/ai/chart-setup/{symbol}")
def get_ai_chart_setup(symbol: str):
    """Return active AI Trader setup and/or strategy engine setup (waiting zone + TP/SL) for chart overlay."""
    sym = symbol.upper().strip()
    all_custom = _load_ai_chart_setups()
    ai_trader_setup = all_custom.get(sym)

    strategy_setup: Optional[Dict[str, Any]] = None
    waiting_zones: List[Dict[str, Any]] = []

    if sym in ("XAUUSD", "GOLD"):
        try:
            from src.analysis.gold_strategy import scan_gold_setup
            gold = scan_gold_setup()
            if "error" not in gold:
                direction = gold.get("recommended_direction", "NEUTRAL")
                nd = gold.get("nearest_demand")
                ns = gold.get("nearest_supply")

                for z in (gold.get("demand_zones") or [])[:2]:
                    waiting_zones.append({
                        "type": "DEMAND",
                        "low": z.get("zone_low"),
                        "high": z.get("zone_high"),
                        "pattern": z.get("pattern", "DEMAND"),
                    })
                for z in (gold.get("supply_zones") or [])[:2]:
                    waiting_zones.append({
                        "type": "SUPPLY",
                        "low": z.get("zone_low"),
                        "high": z.get("zone_high"),
                        "pattern": z.get("pattern", "SUPPLY"),
                    })

                target_zone = ns if direction == "SELL" else (nd if direction == "BUY" else (ns or nd))
                strategy_setup = {
                    "symbol": sym,
                    "direction": direction,
                    "status": gold.get("status", "MONITORING"),
                    "entry_price": gold.get("recommended_entry", 0.0),
                    "stop_loss": gold.get("recommended_sl", 0.0),
                    "take_profit": gold.get("recommended_tp", 0.0),
                    "rr_ratio": gold.get("rr_ratio", 0.0),
                    "zone_low": target_zone.get("zone_low") if target_zone else None,
                    "zone_high": target_zone.get("zone_high") if target_zone else None,
                    "title": f"Gold Strategy: {gold.get('status', 'MONITORING')}",
                    "reason": gold.get("setup_reason", ""),
                    "timeframe": gold.get("trigger_timeframe", "M15"),
                    "source": "GOLD_STRATEGY",
                }
        except Exception as e:
            strategy_setup = {"symbol": sym, "direction": "NEUTRAL", "status": "UNAVAILABLE", "reason": str(e), "source": "GOLD_STRATEGY"}
    elif sym == "BTCUSD":
        try:
            from src.analysis.btc_scalper import scan_btc_1m
            btc = scan_btc_1m()
            if "error" not in btc and btc.get("scalp_setup"):
                sc = btc["scalp_setup"]
                dz = (btc.get("structure") or {}).get("demand_zone")
                strategy_setup = {
                    "symbol": sym,
                    "direction": sc.get("direction", "NEUTRAL"),
                    "status": "SCALP_SETUP",
                    "entry_price": sc.get("entry_price", 0.0),
                    "stop_loss": sc.get("stop_loss", 0.0),
                    "take_profit": sc.get("take_profit", 0.0),
                    "rr_ratio": sc.get("risk_reward_ratio", 0.0),
                    "zone_low": dz.get("price_low") if dz else None,
                    "zone_high": dz.get("price_high") if dz else None,
                    "title": f"BTC 1m Scalp: {sc.get('direction', '')}",
                    "reason": sc.get("narrative", ""),
                    "timeframe": "1m",
                    "source": "BTC_SCALPER",
                }
        except Exception:
            pass
    else:
        try:
            plan = cached_plans.get(sym)
            if plan is None:
                bars_w = data_adapter.get_bars(sym, TimeFrame.WEEK, limit=150)
                bars_d = data_adapter.get_bars(sym, TimeFrame.DAY, limit=500)
                bars_m = data_adapter.get_bars(sym, TimeFrame.M15, limit=50)
                zones = build_sr_zones(sym, bars_d, n_fractal=3)
                plan = evaluate_bounce_setup(sym, bars_w, bars_d, bars_m, zones, settings)
                cached_plans[sym] = plan
            if plan and plan.entry_price > 0:
                strategy_setup = {
                    "symbol": sym,
                    "direction": plan.direction,
                    "status": plan.status.value,
                    "entry_price": plan.entry_price,
                    "stop_loss": plan.stop_loss,
                    "take_profit": plan.take_profit,
                    "rr_ratio": plan.risk_reward_ratio,
                    "zone_low": None,
                    "zone_high": None,
                    "title": f"{plan.strategy_name} ({plan.status.value})",
                    "reason": plan.rejection_reason or "",
                    "timeframe": "1D",
                    "source": "PLAN_ENGINE",
                }
        except Exception:
            pass

    active_setup = ai_trader_setup or strategy_setup
    return {
        "symbol": sym,
        "active_setup": active_setup,
        "ai_trader_setup": ai_trader_setup,
        "strategy_setup": strategy_setup,
        "waiting_zones": waiting_zones,
    }

# ----------------- BACKTESTING & ANALYTICS -----------------
class BacktestRunRequest(BaseModel):
    symbols: Optional[List[str]] = None
    initial_capital_thb: Optional[float] = None
    split_ratio: Optional[float] = 0.70

@app.post("/api/backtest/run")
def run_backtest_endpoint(req: BacktestRunRequest):
    global cached_backtest_report
    cap = req.initial_capital_thb or settings.base_capital_thb
    sym_cfg = getattr(data_adapter, "symbols_config", mock_adapter.symbols_config)
    target_symbols = req.symbols or list(sym_cfg.keys())
    split = req.split_ratio if req.split_ratio is not None else 0.70

    all_trades: List[TradeRecord] = []
    for sym in target_symbols:
        bars_d = data_adapter.get_bars(sym, TimeFrame.DAY, limit=200)
        sym_trades = backtest_engine.run_backtest(
            symbol=sym,
            bars_day=bars_d,
            initial_capital_thb=cap,
            split_ratio=split
        )
        all_trades.extend(sym_trades)

    report = BacktestMetrics.calculate_full_report(all_trades, initial_capital_thb=cap)
    cached_backtest_report = report
    return {"status": "SUCCESS", "report": report}

@app.get("/api/backtest/results")
def get_backtest_results():
    global cached_backtest_report
    if not cached_backtest_report:
        # Auto-run once if empty
        sym_cfg = getattr(data_adapter, "symbols_config", mock_adapter.symbols_config)
        target_symbols = list(sym_cfg.keys())
        all_trades: List[TradeRecord] = []
        for sym in target_symbols:
            bars_d = data_adapter.get_bars(sym, TimeFrame.DAY, limit=200)
            sym_trades = backtest_engine.run_backtest(
                symbol=sym,
                bars_day=bars_d,
                initial_capital_thb=settings.base_capital_thb,
                split_ratio=0.70
            )
            all_trades.extend(sym_trades)
        cached_backtest_report = BacktestMetrics.calculate_full_report(
            all_trades, initial_capital_thb=settings.base_capital_thb
        )
    return cached_backtest_report

# ----------------- MT5 DEMO EXECUTION BRIDGE -----------------
@app.get("/api/mt5/status")
def get_mt5_status():
    global auto_execution_enabled
    res = mt5_client.connect()
    is_connected = mt5_client.is_connected
    acc = mt5_client.account_info if is_connected else {}
    server_str = acc.get("server", "").lower()
    is_demo = acc.get("is_demo", True)
    if "real" in server_str or acc.get("trade_mode") == 2 or acc.get("currency") == "USC":
        is_demo = False

    acc_type_label = "REAL (Cent USC)" if acc.get("currency") == "USC" else ("DEMO" if is_demo else "REAL")
    status_label = f"CONNECTED (Exness {acc_type_label})" if is_connected else "DISCONNECTED (Simulation Mode)"

    return {
        "is_connected": is_connected,
        "status_label": status_label,
        "account_type": "REAL" if not is_demo else "DEMO",
        "is_demo": is_demo,
        "account": mt5_client.account_info if is_connected else {
            "login": "Demo Account",
            "server": "Exness-MT5Trial",
            "currency": "USD",
            "balance": 1000.0,
            "equity": 1000.0,
            "free_margin": 1000.0,
            "leverage": 20.0
        },
        "auto_execution_enabled": auto_execution_enabled,
        "connection_details": res
    }

@app.get("/api/mt5/positions")
def get_mt5_positions():
    # 🛡️ Breakeven Guard Engine: Automatically checks and moves SL to Breakeven when profit >= 1.0x R
    breakeven_locks = []
    try:
        breakeven_locks = mt5_client.check_and_apply_breakeven_locks(min_r_multiple=1.0)
    except Exception as e:
        logger.warning(f"Error checking breakeven locks: {e}")

    return {
        "positions": mt5_client.get_open_positions(),
        "breakeven_locks": breakeven_locks
    }

class ExecuteOrderRequest(BaseModel):
    symbol: str
    direction: str = "BUY"
    volume: float = 0.01
    sl_price: float
    tp_price: float
    comment: Optional[str] = "AutoTrade Entry"
    plan_id: Optional[str] = None

@app.post("/api/mt5/execute")
def execute_order_endpoint(req: ExecuteOrderRequest):
    # Idempotency check
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H")
    if order_reconciler.is_order_duplicate(req.symbol, "1D", now_str, req.direction):
        return {
            "success": False,
            "error": "Idempotency Guard: Order already submitted for this asset in the current bar session."
        }

    # Mandatory Hard SL check
    if req.sl_price <= 0:
        raise HTTPException(status_code=400, detail="Hard Stop Loss is mandatory before sending order.")

    res = mt5_client.send_order(
        symbol=req.symbol.upper(),
        direction=req.direction,
        volume=req.volume,
        sl_price=req.sl_price,
        tp_price=req.tp_price,
        comment=req.comment or "AutoTrade Plan"
    )

    if res.get("success"):
        order_reconciler.record_order_execution(req.symbol, "1D", now_str, req.direction)
        # Update plan status if plan_id passed
        if req.symbol in cached_plans:
            cached_plans[req.symbol].status = PlanStatus.ORDER_PLACED

    return res

@app.post("/api/mt5/close/{ticket}")
def close_order_endpoint(ticket: int):
    return mt5_client.close_position(ticket)

@app.post("/api/mt5/emergency-close-all")
def emergency_close_all_endpoint():
    return mt5_client.emergency_close_all()

@app.post("/api/mt5/toggle-auto")
def toggle_auto_execution():
    global auto_execution_enabled
    auto_execution_enabled = not auto_execution_enabled
    return {"auto_execution_enabled": auto_execution_enabled}

# ----------------- SCREENSHOT & GALLERY -----------------
class CaptureRequest(BaseModel):
    symbol: str
    timeframe: str = "1D"
    event_id: str = "MANUAL_INSPECTION"
    notes: Optional[str] = None

@app.post("/api/capture")
def capture_snapshot(req: CaptureRequest):
    symbol = req.symbol.upper()
    # Fetch 260 bars so MA(50) and MA(200) can be calculated fully
    bars = data_adapter.get_bars(symbol, TimeFrame(req.timeframe), limit=260)
    bars_dict = [b.to_dict() for b in bars]
    
    day_bars = data_adapter.get_bars(symbol, TimeFrame.DAY, limit=100)
    zones = build_sr_zones(symbol, day_bars, n_fractal=3)
    zones_dict = [z.to_dict() for z in zones]

    meta = screenshot_service.capture_chart(
        symbol=symbol,
        timeframe=req.timeframe,
        event_id=req.event_id,
        bars_data=bars_dict,
        zones_data=zones_dict,
        extra_metadata={"notes": req.notes}
    )
    return {"status": "CAPTURED", "metadata": meta}

@app.get("/api/screenshots")
def get_screenshots_gallery(symbol: Optional[str] = None):
    return {
        "screenshots": screenshot_service.list_screenshots(symbol=symbol)
    }

# ----------------- SETTINGS MANAGEMENT -----------------
class SettingsUpdate(BaseModel):
    base_capital_thb: Optional[float] = None
    max_leverage: Optional[float] = None
    risk_per_trade_percent: Optional[float] = None
    allow_overnight: Optional[bool] = None
    allow_weekend: Optional[bool] = None
    execution_enabled: Optional[bool] = None

@app.post("/api/settings")
def update_settings(update: SettingsUpdate):
    global auto_execution_enabled
    if update.base_capital_thb is not None:
        settings.base_capital_thb = update.base_capital_thb
    if update.max_leverage is not None:
        settings.max_leverage = update.max_leverage
    if update.risk_per_trade_percent is not None:
        settings.risk_per_trade_percent = update.risk_per_trade_percent
    if update.allow_overnight is not None:
        settings.allow_overnight = update.allow_overnight
    if update.allow_weekend is not None:
        settings.allow_weekend = update.allow_weekend
    if update.execution_enabled is not None:
        settings.execution_enabled = update.execution_enabled
        auto_execution_enabled = update.execution_enabled
    return {"status": "UPDATED", "settings": {
        "base_capital_thb": settings.base_capital_thb,
        "max_leverage": settings.max_leverage,
        "risk_per_trade_percent": settings.risk_per_trade_percent,
        "allow_overnight": settings.allow_overnight,
        "allow_weekend": settings.allow_weekend,
        "execution_enabled": settings.execution_enabled
    }}

# ----------------- MULTI-PORTFOLIO TRADING JOURNAL PRO ENDPOINTS -----------------

class PortfolioCreateReq(BaseModel):
    id: str
    name: str
    account_login: Optional[str] = None
    initial_capital: float = 1000.0
    risk_per_trade_percent: float = 1.0
    currency: str = "USD"
    description: Optional[str] = None

class JournalTradeCreateReq(BaseModel):
    trade_date: Optional[str] = None
    symbol: str
    direction: str
    risk_usd: float = 10.0
    exit_1: Optional[float] = None
    exit_2: Optional[float] = None
    exit_3: Optional[float] = None
    total_pnl: Optional[float] = None
    r_multiple: Optional[float] = None
    setup: Optional[str] = None
    tradingview_url: Optional[str] = None
    outcome: Optional[str] = None
    comment: Optional[str] = None

@app.get("/api/portfolios")
def list_portfolios(db: Session = Depends(get_db)):
    mt5_acc = get_connected_mt5_account_info()
    active_mt5_login = str(mt5_acc["login"]) if mt5_acc.get("connected") and mt5_acc.get("login") else None
    recommended_port = ensure_portfolio_for_mt5_account(db, mt5_acc) if active_mt5_login else None

    ports = db.query(PortfolioModel).order_by(PortfolioModel.created_at.asc()).all()
    if not ports:
        default_port = PortfolioModel(
            id="port_main",
            name="Main Portfolio (Trading Journal Pro)",
            account_login="Default",
            initial_capital=1000.0,
            risk_per_trade_percent=1.0,
            currency="USD",
            description="พอร์ตหลักตามโครงสร้าง Trading Journal Pro Template"
        )
        db.add(default_port)
        db.commit()
        db.refresh(default_port)
        ports = [default_port]
    
    res = []
    for p in ports:
        trade_count = db.query(JournalTradeModel).filter(JournalTradeModel.portfolio_id == p.id).count()
        res.append({
            "id": p.id,
            "name": p.name,
            "account_login": p.account_login,
            "initial_capital": p.initial_capital,
            "risk_per_trade_percent": p.risk_per_trade_percent,
            "currency": p.currency,
            "description": p.description,
            "trades_count": trade_count
        })
    return {
        "portfolios": res,
        "active_mt5_login": active_mt5_login,
        "recommended_portfolio_id": recommended_port.id if recommended_port else (res[0]["id"] if res else None),
    }

@app.post("/api/portfolios")
def create_or_update_portfolio(req: PortfolioCreateReq, db: Session = Depends(get_db)):
    existing = db.query(PortfolioModel).filter(PortfolioModel.id == req.id).first()
    if existing:
        existing.name = req.name
        existing.account_login = req.account_login
        existing.initial_capital = req.initial_capital
        existing.risk_per_trade_percent = req.risk_per_trade_percent
        existing.currency = req.currency
        existing.description = req.description
        db.commit()
        db.refresh(existing)
        return {"status": "UPDATED", "portfolio": {"id": existing.id, "name": existing.name}}
    else:
        new_p = PortfolioModel(
            id=req.id,
            name=req.name,
            account_login=req.account_login,
            initial_capital=req.initial_capital,
            risk_per_trade_percent=req.risk_per_trade_percent,
            currency=req.currency,
            description=req.description
        )
        db.add(new_p)
        db.commit()
        db.refresh(new_p)
        return {"status": "CREATED", "portfolio": {"id": new_p.id, "name": new_p.name}}

@app.get("/api/portfolios/{portfolio_id}/dashboard")
def get_portfolio_dashboard(portfolio_id: str, db: Session = Depends(get_db)):
    port = db.query(PortfolioModel).filter(PortfolioModel.id == portfolio_id).first()
    if not port:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    trades = db.query(JournalTradeModel).filter(
        JournalTradeModel.portfolio_id == portfolio_id
    ).order_by(JournalTradeModel.trade_date.asc(), JournalTradeModel.id.asc()).all()

    total_trades = len(trades)
    total_pnl = sum(t.total_pnl for t in trades)
    total_r = sum(t.r_multiple for t in trades)
    current_balance = port.initial_capital + total_pnl

    wins = [t for t in trades if t.outcome == "W" or (t.outcome not in ["L", "BE"] and t.r_multiple > 0)]
    losses = [t for t in trades if t.outcome == "L" or (t.outcome not in ["W", "BE"] and t.r_multiple < 0)]
    be_trades = [t for t in trades if t.outcome == "BE" or (t not in wins and t not in losses)]

    resolved = len(wins) + len(losses)
    win_rate = round((len(wins) / resolved * 100.0), 1) if resolved > 0 else 0.0
    avg_win_r = round(sum(t.r_multiple for t in wins) / len(wins), 2) if wins else 0.0
    avg_loss_r = round(sum(t.r_multiple for t in losses) / len(losses), 2) if losses else 0.0
    avg_win_pnl = round(sum(t.total_pnl for t in wins) / len(wins), 2) if wins else 0.0
    avg_loss_pnl = round(sum(t.total_pnl for t in losses) / len(losses), 2) if losses else 0.0
    best_trade_r = round(max((t.r_multiple for t in trades), default=0.0), 2)
    worst_trade_r = round(min((t.r_multiple for t in trades), default=0.0), 2)
    best_trade_pnl = round(max((t.total_pnl for t in trades), default=0.0), 2)
    worst_trade_pnl = round(min((t.total_pnl for t in trades), default=0.0), 2)
    avg_r_per_trade = round(total_r / total_trades, 2) if total_trades > 0 else 0.0
    avg_pnl_per_trade = round(total_pnl / total_trades, 2) if total_trades > 0 else 0.0

    # Monthly performance
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    monthly_data = [{"month": m, "name": month_names[m-1], "total_r": 0.0, "trades": 0, "pnl": 0.0} for m in range(1, 13)]
    for t in trades:
        m_idx = t.trade_date.month - 1
        monthly_data[m_idx]["total_r"] = round(monthly_data[m_idx]["total_r"] + t.r_multiple, 2)
        monthly_data[m_idx]["trades"] += 1
        monthly_data[m_idx]["pnl"] = round(monthly_data[m_idx]["pnl"] + t.total_pnl, 2)

    active_months = [m for m in monthly_data if m["trades"] > 0]
    best_month = max(active_months, key=lambda x: x["total_r"])["name"] if active_months else "-"

    # Cumulative R & PnL Curve
    cumulative_curve = []
    running_r = 0.0
    running_pnl = 0.0
    for idx, t in enumerate(trades):
        running_r += t.r_multiple
        running_pnl += t.total_pnl
        cumulative_curve.append({
            "trade_no": idx + 1,
            "date": t.trade_date.strftime("%Y-%m-%d"),
            "r": round(t.r_multiple, 2),
            "cumulative_r": round(running_r, 2),
            "cumulative_pnl": round(running_pnl, 2),
            "symbol": t.symbol
        })

    # Setup Breakdown
    setup_groups: Dict[str, List[JournalTradeModel]] = {}
    for t in trades:
        s_name = t.setup.strip() if t.setup and t.setup.strip() else "Playbook General"
        if s_name not in setup_groups:
            setup_groups[s_name] = []
        setup_groups[s_name].append(t)

    setup_breakdown = []
    for s_name, s_trades in setup_groups.items():
        s_wins = [t for t in s_trades if t.outcome == "W" or (t.outcome not in ["L", "BE"] and t.r_multiple > 0)]
        s_losses = [t for t in s_trades if t.outcome == "L" or (t.outcome not in ["W", "BE"] and t.r_multiple < 0)]
        s_res = len(s_wins) + len(s_losses)
        s_wr = round(len(s_wins) / s_res * 100.0, 1) if s_res > 0 else 0.0
        s_tot_r = round(sum(t.r_multiple for t in s_trades), 2)
        s_avg_r = round(s_tot_r / len(s_trades), 2) if s_trades else 0.0
        s_tot_pnl = round(sum(t.total_pnl for t in s_trades), 2)
        s_avg_pnl = round(s_tot_pnl / len(s_trades), 2) if s_trades else 0.0
        setup_breakdown.append({
            "setup": s_name,
            "trades": len(s_trades),
            "win_rate": s_wr,
            "avg_r": s_avg_r,
            "total_r": s_tot_r,
            "total_pnl": s_tot_pnl,
            "avg_pnl": s_avg_pnl
        })

    # Sort setup breakdown by total_r descending
    setup_breakdown.sort(key=lambda x: x["total_r"], reverse=True)

    # Calendar Daily Heatmap (YYYY-MM-DD -> daily stats)
    calendar_daily: Dict[str, Dict[str, Any]] = {}
    for t in trades:
        d_str = t.trade_date.strftime("%Y-%m-%d")
        if d_str not in calendar_daily:
            calendar_daily[d_str] = {"date": d_str, "total_r": 0.0, "trades": 0, "pnl": 0.0, "wins": 0, "losses": 0}
        calendar_daily[d_str]["total_r"] = round(calendar_daily[d_str]["total_r"] + t.r_multiple, 2)
        calendar_daily[d_str]["pnl"] = round(calendar_daily[d_str]["pnl"] + t.total_pnl, 2)
        calendar_daily[d_str]["trades"] += 1
        if t.outcome == "W" or (t.outcome not in ["L", "BE"] and t.r_multiple > 0):
            calendar_daily[d_str]["wins"] += 1
        elif t.outcome == "L" or (t.outcome not in ["W", "BE"] and t.r_multiple < 0):
            calendar_daily[d_str]["losses"] += 1

    curr = port.currency or "USD"
    is_cent = (curr.upper() == "USC")

    def to_usd(val: float) -> float:
        if is_cent:
            return round(val / 100.0, 2)
        elif curr == "THB":
            return round(val / 35.0, 2)
        return round(val, 2)

    def to_thb(val: float) -> float:
        if is_cent:
            return round((val / 100.0) * 35.0, 2)
        elif curr == "USD":
            return round(val * 35.0, 2)
        return round(val, 2)

    return {
        "portfolio": {
            "id": port.id,
            "name": port.name,
            "account_login": port.account_login,
            "initial_capital": port.initial_capital,
            "initial_capital_usd": to_usd(port.initial_capital),
            "initial_capital_thb": to_thb(port.initial_capital),
            "risk_per_trade_percent": port.risk_per_trade_percent,
            "risk_amount_per_trade": round(port.initial_capital * (port.risk_per_trade_percent / 100.0), 2),
            "currency": curr,
            "description": port.description
        },
        "kpi": {
            "current_balance": round(current_balance, 2),
            "current_balance_usd": to_usd(current_balance),
            "current_balance_thb": to_thb(current_balance),
            "currency": curr,
            "total_pnl": round(total_pnl, 2),
            "total_pnl_usd": to_usd(total_pnl),
            "total_pnl_thb": to_thb(total_pnl),
            "total_r": round(total_r, 2),
            "total_trades": total_trades,
            "win_rate": win_rate,
            "win_count": len(wins),
            "loss_count": len(losses),
            "be_count": len(be_trades),
            "avg_win_r": avg_win_r,
            "avg_loss_r": avg_loss_r,
            "avg_win_pnl": avg_win_pnl,
            "avg_loss_pnl": avg_loss_pnl
        },
        "quick_stats": {
            "best_trade_r": best_trade_r,
            "worst_trade_r": worst_trade_r,
            "best_trade_pnl": best_trade_pnl,
            "worst_trade_pnl": worst_trade_pnl,
            "best_month": best_month,
            "avg_r_per_trade": avg_r_per_trade,
            "avg_pnl_per_trade": avg_pnl_per_trade
        },
        "monthly_performance": monthly_data,
        "cumulative_curve": cumulative_curve,
        "setup_breakdown": setup_breakdown,
        "calendar_daily": calendar_daily
    }

@app.get("/api/portfolios/{portfolio_id}/trades")
def list_portfolio_trades(
    portfolio_id: str,
    symbol: Optional[str] = None,
    setup: Optional[str] = None,
    outcome: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    query = db.query(JournalTradeModel).filter(JournalTradeModel.portfolio_id == portfolio_id)
    if symbol:
        query = query.filter(JournalTradeModel.symbol == symbol.upper())
    if setup:
        query = query.filter(JournalTradeModel.setup == setup)
    if outcome:
        query = query.filter(JournalTradeModel.outcome == outcome.upper())

    trades = query.order_by(JournalTradeModel.trade_date.desc(), JournalTradeModel.id.desc()).limit(limit).all()
    
    # Calculate cumulative R for response
    # Fetch all for proper cumulative calculation
    all_trades_asc = db.query(JournalTradeModel).filter(
        JournalTradeModel.portfolio_id == portfolio_id
    ).order_by(JournalTradeModel.trade_date.asc(), JournalTradeModel.id.asc()).all()

    cum_map = {}
    running_r = 0.0
    for idx, t in enumerate(all_trades_asc):
        running_r = round(running_r + t.r_multiple, 2)
        cum_map[t.id] = running_r

    return {
        "portfolio_id": portfolio_id,
        "total_count": len(all_trades_asc),
        "trades": [
            {
                "id": t.id,
                "trade_no": t.trade_no or t.id,
                "trade_date": t.trade_date.strftime("%Y-%m-%d %H:%M") if t.trade_date else "",
                "symbol": t.symbol,
                "direction": t.direction,
                "risk_usd": t.risk_usd,
                "exit_1": t.exit_1,
                "exit_2": t.exit_2,
                "exit_3": t.exit_3,
                "total_pnl": t.total_pnl,
                "r_multiple": t.r_multiple,
                "cumulative_r": cum_map.get(t.id, 0.0),
                "setup": t.setup,
                "tradingview_url": t.tradingview_url,
                "outcome": t.outcome,
                "comment": t.comment,
                "mt5_ticket": t.mt5_ticket
            }
            for t in trades
        ]
    }

@app.post("/api/portfolios/{portfolio_id}/trades")
def create_portfolio_trade(portfolio_id: str, req: JournalTradeCreateReq, db: Session = Depends(get_db)):
    port = db.query(PortfolioModel).filter(PortfolioModel.id == portfolio_id).first()
    if not port:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    trade_dt = datetime.now(timezone.utc)
    if req.trade_date:
        try:
            if "T" in req.trade_date:
                trade_dt = datetime.fromisoformat(req.trade_date)
            else:
                trade_dt = datetime.strptime(req.trade_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            trade_dt = datetime.now(timezone.utc)

    # Calculate Total P/L if not provided, or sum exit levels
    pnl = req.total_pnl
    if pnl is None:
        exits = [x for x in [req.exit_1, req.exit_2, req.exit_3] if x is not None]
        pnl = sum(exits) if exits else 0.0

    risk = req.risk_usd if (req.risk_usd and req.risk_usd > 0) else round(port.initial_capital * (port.risk_per_trade_percent / 100.0), 2)
    
    r_val = req.r_multiple
    if r_val is None:
        r_val = round(pnl / risk, 2) if risk > 0 else 0.0

    outcome = req.outcome
    if not outcome:
        from src.execution.mt5_journal_sync import classify_trade_outcome
        outcome = classify_trade_outcome(r_val)

    count_existing = db.query(JournalTradeModel).filter(JournalTradeModel.portfolio_id == portfolio_id).count()

    new_trade = JournalTradeModel(
        portfolio_id=portfolio_id,
        trade_no=count_existing + 1,
        trade_date=trade_dt,
        symbol=req.symbol.upper(),
        direction=req.direction.upper(),
        risk_usd=risk,
        exit_1=req.exit_1,
        exit_2=req.exit_2,
        exit_3=req.exit_3,
        total_pnl=round(pnl, 2),
        r_multiple=round(r_val, 2),
        setup=req.setup or "Playbook 1",
        tradingview_url=req.tradingview_url,
        outcome=outcome,
        comment=req.comment
    )
    db.add(new_trade)
    db.commit()
    db.refresh(new_trade)

    return {"status": "SUCCESS", "trade_id": new_trade.id, "r_multiple": new_trade.r_multiple}

@app.delete("/api/portfolios/{portfolio_id}/trades/{trade_id}")
def delete_portfolio_trade(portfolio_id: str, trade_id: int, db: Session = Depends(get_db)):
    t = db.query(JournalTradeModel).filter(
        JournalTradeModel.portfolio_id == portfolio_id,
        JournalTradeModel.id == trade_id
    ).first()
    if not t:
        raise HTTPException(status_code=404, detail="Trade not found")
    db.delete(t)
    db.commit()
    return {"status": "DELETED", "trade_id": trade_id}

@app.post("/api/portfolios/{portfolio_id}/seed-sample")
def seed_sample_journal_data(portfolio_id: str, db: Session = Depends(get_db)):
    """Populates realistic historical trades for demonstration matching Excel template setups."""
    port = db.query(PortfolioModel).filter(PortfolioModel.id == portfolio_id).first()
    if not port:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    existing_count = db.query(JournalTradeModel).filter(JournalTradeModel.portfolio_id == portfolio_id).count()
    if existing_count > 0:
        return {"status": "SKIPPED", "message": f"Portfolio already has {existing_count} trades"}

    sample_trades = [
        {"d": "2026-01-05", "sym": "XAUUSD", "dir": "BUY", "risk": 10.0, "pnl": 25.0, "r": 2.5, "setup": "Playbook 1 (Breakout Retest)", "out": "W", "comm": "Clean 15m retest of daily support zone."},
        {"d": "2026-01-08", "sym": "EURUSD", "dir": "SELL", "risk": 10.0, "pnl": -10.0, "r": -1.0, "setup": "Playbook 2 (Trend Pullback)", "out": "L", "comm": "Stopped out before London open expansion."},
        {"d": "2026-01-12", "sym": "XAUUSD", "dir": "BUY", "risk": 10.0, "pnl": 32.0, "r": 3.2, "setup": "Playbook 1 (Breakout Retest)", "out": "W", "comm": "TP reached at major liquidity high."},
        {"d": "2026-01-16", "sym": "BTCUSD", "dir": "BUY", "risk": 10.0, "pnl": -10.0, "r": -1.0, "setup": "Playbook 3 (Fibo Confluence)", "out": "L", "comm": "Failed bounce at 0.618 level."},
        {"d": "2026-01-20", "sym": "NVDA", "dir": "BUY", "risk": 10.0, "pnl": 18.0, "r": 1.8, "setup": "Playbook 2 (Trend Pullback)", "out": "W", "comm": "Followed tech sector momentum."},
        {"d": "2026-01-23", "sym": "XAUUSD", "dir": "SELL", "risk": 10.0, "pnl": 0.0, "r": 0.0, "setup": "Playbook 4 (Reversal Zone)", "out": "BE", "comm": "Closed early ahead of high impact news."},
        {"d": "2026-02-02", "sym": "BTCUSD", "dir": "BUY", "risk": 10.0, "pnl": 41.0, "r": 4.1, "setup": "Playbook 1 (Breakout Retest)", "out": "W", "comm": "Explosive breakout on weekend volume."},
        {"d": "2026-02-05", "sym": "AAPL", "dir": "BUY", "risk": 10.0, "pnl": 21.0, "r": 2.1, "setup": "Playbook 2 (Trend Pullback)", "out": "W", "comm": "Bounced off Daily 50 EMA."},
        {"d": "2026-02-10", "sym": "XAUUSD", "dir": "SELL", "risk": 10.0, "pnl": -10.0, "r": -1.0, "setup": "Playbook 4 (Reversal Zone)", "out": "L", "comm": "Strong dollar divergence squeeze."},
        {"d": "2026-02-16", "sym": "MSFT", "dir": "BUY", "risk": 10.0, "pnl": 15.0, "r": 1.5, "setup": "Playbook 3 (Fibo Confluence)", "out": "W", "comm": "Target hit at pre-market high."}
    ]

    for idx, item in enumerate(sample_trades):
        trade_dt = datetime.strptime(item["d"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        jt = JournalTradeModel(
            portfolio_id=portfolio_id,
            trade_no=idx + 1,
            trade_date=trade_dt,
            symbol=item["sym"],
            direction=item["dir"],
            risk_usd=item["risk"],
            total_pnl=item["pnl"],
            r_multiple=item["r"],
            setup=item["setup"],
            outcome=item["out"],
            comment=item["comm"]
        )
        db.add(jt)
    db.commit()
    return {"status": "SEEDED", "count": len(sample_trades)}

@app.post("/api/portfolios/{portfolio_id}/sync-mt5")
def sync_portfolio_with_mt5(portfolio_id: str, days_back: int = Query(90), db: Session = Depends(get_db)):
    result = sync_mt5_deals_to_portfolio(portfolio_id=portfolio_id, db=db, days_back=days_back)
    if result.get("status") == "ACCOUNT_MISMATCH":
        raise HTTPException(status_code=409, detail=result.get("message"))
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result

@app.get("/api/portfolios/{portfolio_id}/mt5-status")
def get_portfolio_mt5_status(portfolio_id: str, db: Session = Depends(get_db)):
    port = db.query(PortfolioModel).filter(PortfolioModel.id == portfolio_id).first()
    if not port:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    mt5_info = get_connected_mt5_account_info()
    matches_account = (
        mt5_info.get("connected", False) and 
        (not port.account_login or port.account_login == "Default" or str(port.account_login) == str(mt5_info.get("login")))
    )
    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": port.name,
        "portfolio_account": port.account_login,
        "mt5_info": mt5_info,
        "matches_account": matches_account
    }


