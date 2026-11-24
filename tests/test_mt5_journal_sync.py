import pytest
from fastapi.testclient import TestClient
from src.web.app import app
from src.storage.database import SessionLocal, init_db
from src.storage.models import PortfolioModel, JournalTradeModel
from src.execution.mt5_journal_sync import sync_mt5_deals_to_portfolio, get_connected_mt5_account_info

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_teardown():
    init_db()
    db = SessionLocal()
    db.query(JournalTradeModel).filter(JournalTradeModel.portfolio_id == "test_mt5_port").delete()
    db.query(PortfolioModel).filter(PortfolioModel.id == "test_mt5_port").delete()
    db.commit()
    db.close()
    yield

def test_mt5_status_endpoint():
    # 1. Create a portfolio linked to MT5
    db = SessionLocal()
    port = PortfolioModel(
        id="test_mt5_port",
        name="Test MT5 Live Sync",
        account_login="Default",
        initial_capital=1000.0,
        risk_per_trade_percent=1.0,
        currency="USD"
    )
    db.add(port)
    db.commit()
    db.close()

    # 2. Check MT5 status endpoint
    res = client.get("/api/portfolios/test_mt5_port/mt5-status")
    assert res.status_code == 200
    data = res.json()
    assert data["portfolio_id"] == "test_mt5_port"
    assert "mt5_info" in data
    # MT5 is running in this environment
    if data["mt5_info"]["connected"]:
        assert data["matches_account"] is True
        assert len(data["mt5_info"]["login"]) > 0

def test_mt5_deal_sync_and_duplicate_prevention():
    db = SessionLocal()
    port = PortfolioModel(
        id="test_mt5_port",
        name="Test MT5 Live Sync",
        account_login="Default",
        initial_capital=1000.0,
        risk_per_trade_percent=1.0,
        currency="USD"
    )
    db.add(port)
    db.commit()
    db.close()

    # Call sync endpoint
    res = client.post("/api/portfolios/test_mt5_port/sync-mt5?days_back=90")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"

    db = SessionLocal()
    trades = db.query(JournalTradeModel).filter(JournalTradeModel.portfolio_id == "test_mt5_port").all()
    count_first_sync = len(trades)
    
    # If MT5 has closed deals (we know 2 closing deals exist on this account)
    if data["synced_count"] > 0:
        assert count_first_sync == data["synced_count"]
        first_trade = trades[0]
        assert first_trade.mt5_ticket is not None
        assert first_trade.r_multiple is not None
        assert first_trade.total_pnl is not None
        assert first_trade.symbol in ["XAUUSD", "EURUSD", "BTCUSD", "XAUUSDc"]

    # 3. Second sync: must prevent duplicates
    res_second = client.post("/api/portfolios/test_mt5_port/sync-mt5?days_back=90")
    assert res_second.status_code == 200
    data_second = res_second.json()
    assert data_second["status"] == "SUCCESS"
    assert data_second["synced_count"] == 0 # No new duplicates added!

    trades_second = db.query(JournalTradeModel).filter(JournalTradeModel.portfolio_id == "test_mt5_port").all()
    assert len(trades_second) == count_first_sync

    # 4. Verify Dashboard metrics updated with MT5 trades
    dash_res = client.get("/api/portfolios/test_mt5_port/dashboard")
    assert dash_res.status_code == 200
    dash_data = dash_res.json()
    assert dash_data["kpi"]["total_trades"] == count_first_sync
    db.close()
