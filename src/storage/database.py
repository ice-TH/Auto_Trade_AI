from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from config.settings import settings
from src.storage.models import Base

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def _migrate_sqlite_columns():
    """Idempotently add newer columns (like account_login) to existing SQLite tables."""
    if "sqlite" not in settings.database_url:
        return
    migrations = [
        ("plans", "account_login", "VARCHAR(32)"),
        ("audit_logs", "account_login", "VARCHAR(32)"),
        ("trade_history", "account_login", "VARCHAR(32)"),
        ("portfolios", "account_login", "VARCHAR(32)"),
    ]
    with engine.begin() as conn:
        for table_name, col_name, col_type in migrations:
            rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            if not rows:
                continue
            existing_cols = {r[1] for r in rows}
            if col_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))

def init_db():
    """Create all database tables and apply lightweight SQLite column migrations."""
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_columns()

def get_db():
    """Dependency helper for FastAPI endpoints."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
