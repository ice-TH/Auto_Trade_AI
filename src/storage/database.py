from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from config.settings import settings
from src.storage.models import Base

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)

def get_db():
    """Dependency helper for FastAPI endpoints."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
