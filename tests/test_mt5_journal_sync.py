import pytest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.web.app import app
from src.storage.database import SessionLocal, init_db
from src.storage.models import PortfolioModel, JournalTradeModel
from src.execution import mt5_journal_sync
from src.execution.mt5_journal_sync import (
    sync_mt5_deals_to_portfolio,
    get_connected_mt5_account_info,
    ensure_portfolio_for_mt5_account,
)

client = TestClient(app)

TEST_PORTFOLIO_IDS = ["test_mt5_port", "test_mt5_port_real", "port_999888777"]


def _cleanup_test_portfolios():
    db = SessionLocal()
    try:
        db.query(JournalTradeModel).filter(JournalTradeModel.portfolio_id.in_(TEST_PORTFOLIO_IDS)).delete(synchronize_session=False)
        db.query(PortfolioModel).filter(PortfolioModel.id.in_(TEST_PORTFOLIO_IDS)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_teardown():
    init_db()
    _cleanup_test_portfolios()
    yield
    _cleanup_test_portfolios()

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


def test_sync_blocks_account_mismatch():
    """Syncing a portfolio bound to account #160219615 while MT5 is on #434552387 must be blocked (HTTP 409)."""
    db = SessionLocal()
    port = PortfolioModel(
        id="test_mt5_port_real",
        name="Real Cent Account",
        account_login="160219615",
        initial_capital=1500.0,
        risk_per_trade_percent=1.0,
        currency="USC",
    )
    db.add(port)
    db.commit()
    db.close()

    fake_acc = SimpleNamespace(
        login=434552387,
        server="Exness-MT5Trial",
        currency="USD",
        balance=177.13,
        equity=177.13,
    )
    fake_mt5 = SimpleNamespace(
        initialize=lambda: True,
        account_info=lambda: fake_acc,
        history_deals_get=lambda *args, **kwargs: [],
    )

    with patch.object(mt5_journal_sync, "MT5_AVAILABLE", True), patch.object(mt5_journal_sync, "mt5", fake_mt5):
        res = client.post("/api/portfolios/test_mt5_port_real/sync-mt5?days_back=90")
        assert res.status_code == 409
        assert "160219615" in res.json()["detail"]
        assert "434552387" in res.json()["detail"]

    # Verify portfolio metadata and trades were NOT overwritten
    db = SessionLocal()
    try:
        refreshed = db.query(PortfolioModel).filter(PortfolioModel.id == "test_mt5_port_real").first()
        assert refreshed.currency == "USC"
        assert refreshed.initial_capital == 1500.0
        assert refreshed.account_login == "160219615"
        assert db.query(JournalTradeModel).filter(JournalTradeModel.portfolio_id == "test_mt5_port_real").count() == 0
    finally:
        db.close()


def test_ensure_portfolio_for_mt5_account_creates_isolated_portfolio():
    """Connecting a new MT5 account auto-provisions an isolated portfolio once and is idempotent."""
    db = SessionLocal()
    try:
        mt5_info = {
            "connected": True,
            "login": "999888777",
            "server": "Exness-MT5Trial",
            "currency": "USD",
            "balance": 250.5,
            "equity": 250.5,
            "is_cent": False,
            "is_demo": True,
        }
        p1 = ensure_portfolio_for_mt5_account(db, mt5_info)
        assert p1 is not None
        assert p1.id == "port_999888777"
        assert p1.account_login == "999888777"
        assert p1.currency == "USD"
        assert p1.initial_capital == 250.5

        # Calling again returns the same portfolio without duplicating
        p2 = ensure_portfolio_for_mt5_account(db, mt5_info)
        assert p2.id == p1.id
        count = db.query(PortfolioModel).filter(PortfolioModel.account_login == "999888777").count()
        assert count == 1
    finally:
        db.close()
