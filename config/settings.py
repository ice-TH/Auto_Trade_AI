from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    
    # Storage
    data_dir: Path = BASE_DIR / "data_store"
    screenshots_dir: Path = BASE_DIR / "screenshots"
    database_url: str = f"sqlite:///{BASE_DIR / 'data_store' / 'autotrade.db'}"
    
    # Trading & Risk Controls (Defaults based on user agreement)
    trading_mode: str = "LIVE"  # READ_ONLY, DEMO, LIVE
    execution_enabled: bool = True
    base_capital_thb: float = 3000.0
    max_leverage: float = 5.0  # Max notional position value / Capital <= 5.0
    risk_per_trade_percent: float = 2.0
    max_daily_loss_percent: float = 5.0
    min_risk_reward_ratio: float = 1.5
    allow_overnight: bool = True
    allow_weekend: bool = True
    
    # Market Data
    data_source: str = "MOCK"  # MOCK or WEBULL_OPENAPI
    webull_app_key: str = ""
    webull_app_secret: str = ""
    webull_api_endpoint: str = "https://api.webull.com"
    
    # MetaTrader 5
    mt5_path: str = r"C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe"
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = "Exness-MT5Trial1"

settings = Settings()

# Ensure directories exist
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.screenshots_dir.mkdir(parents=True, exist_ok=True)
