from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

class ManualZoneModel(Base):
    __tablename__ = "manual_zones"
    
    id = Column(String(64), primary_key=True)
    symbol = Column(String(16), nullable=False, index=True)
    timeframe = Column(String(8), nullable=False)
    price_high = Column(Float, nullable=False)
    price_low = Column(Float, nullable=False)
    label = Column(String(64), default="Manual Zone")
    zone_type = Column(String(16), default="SUPPORT")
    is_locked = Column(Boolean, default=False)
    author = Column(String(32), default="User")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class PlanModel(Base):
    __tablename__ = "plans"
    
    plan_id = Column(String(64), primary_key=True)
    strategy_version = Column(String(16), default="1.0.0")
    account_login = Column(String(32), nullable=True, index=True) # Isolated per MT5 Account
    symbol = Column(String(16), nullable=False, index=True)
    timeframe = Column(String(8), nullable=False)
    direction = Column(String(8), nullable=False) # LONG or SHORT
    status = Column(String(32), nullable=False, default="WAITING_CONDITIONS")
    day_zone_id = Column(String(64), nullable=True)
    week_context = Column(Text, nullable=True)
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    risk_thb = Column(Float, nullable=True)
    lot_size = Column(Float, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class AuditLogModel(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    account_login = Column(String(32), nullable=True, index=True) # Isolated per MT5 Account
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    event_type = Column(String(32), nullable=False)
    symbol = Column(String(16), nullable=True)
    payload_json = Column(Text, nullable=True)

class TradeHistoryModel(Base):
    __tablename__ = "trade_history"
    
    ticket = Column(Integer, primary_key=True)
    order_id = Column(Integer, nullable=True)
    account_login = Column(String(32), nullable=True, index=True)
    symbol = Column(String(16), nullable=False, index=True)
    direction = Column(String(8), nullable=False) # BUY or SELL
    volume = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    close_price = Column(Float, nullable=False)
    sl_price = Column(Float, nullable=True)
    tp_price = Column(Float, nullable=True)
    profit_usd = Column(Float, nullable=False)
    profit_thb = Column(Float, nullable=False)
    outcome = Column(String(16), nullable=False) # WIN, LOSS, BREAKEVEN
    exit_reason = Column(String(64), nullable=True) # SL_HIT, TP_HIT, MANUAL_CLOSE
    root_cause = Column(Text, nullable=True)
    lesson_learned = Column(Text, nullable=True)
    case_file = Column(String(128), nullable=True)
    close_time = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    payload_json = Column(Text, nullable=True)

class PortfolioModel(Base):
    __tablename__ = "portfolios"
    
    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    account_login = Column(String(32), nullable=True, index=True)
    initial_capital = Column(Float, default=1000.0)
    risk_per_trade_percent = Column(Float, default=1.0)
    currency = Column(String(8), default="USD")
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class JournalTradeModel(Base):
    __tablename__ = "journal_trades"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(String(64), nullable=False, index=True)
    trade_no = Column(Integer, nullable=True)
    trade_date = Column(DateTime, nullable=False, index=True)
    symbol = Column(String(16), nullable=False, index=True)
    direction = Column(String(8), nullable=False) # BUY, SELL, LONG, SHORT
    risk_usd = Column(Float, nullable=False, default=10.0)
    exit_1 = Column(Float, nullable=True)
    exit_2 = Column(Float, nullable=True)
    exit_3 = Column(Float, nullable=True)
    total_pnl = Column(Float, nullable=False, default=0.0)
    r_multiple = Column(Float, nullable=False, default=0.0)
    setup = Column(String(64), nullable=True)
    tradingview_url = Column(String(256), nullable=True)
    outcome = Column(String(8), nullable=False, default="BE") # W, L, BE
    comment = Column(Text, nullable=True)
    mt5_ticket = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

