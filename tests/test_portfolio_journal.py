import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from src.web.app import app
from src.storage.database import SessionLocal, init_db
from src.storage.models import PortfolioModel, JournalTradeModel

client = TestClient(app)

def _cleanup_journal_tests():
    db = SessionLocal()
    try:
        db.query(JournalTradeModel).filter(JournalTradeModel.portfolio_id.in_(["test_port_a", "test_port_b"])).delete(synchronize_session=False)
        db.query(PortfolioModel).filter(PortfolioModel.id.in_(["test_port_a", "test_port_b"])).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    _cleanup_journal_tests()
    yield
    _cleanup_journal_tests()

def test_portfolio_creation_and_listing():
    # 1. Create Portfolio A
    res_a = client.post("/api/portfolios", json={
        "id": "test_port_a",
        "name": "Test Swing Gold",
        "initial_capital": 2000.0,
        "risk_per_trade_percent": 1.5,
        "currency": "USD",
        "description": "Gold Swing Portfolio"
    })
    assert res_a.status_code == 200
    assert res_a.json()["status"] == "CREATED"

    # 2. Create Portfolio B
    res_b = client.post("/api/portfolios", json={
        "id": "test_port_b",
        "name": "Test Scalp BTC",
        "initial_capital": 5000.0,
        "risk_per_trade_percent": 2.0,
        "currency": "USD"
    })
    assert res_b.status_code == 200
    assert res_b.json()["status"] == "CREATED"

    # 3. List Portfolios
    list_res = client.get("/api/portfolios")
    assert list_res.status_code == 200
    ports = {p["id"]: p for p in list_res.json()["portfolios"]}
    assert "test_port_a" in ports
    assert "test_port_b" in ports
    assert ports["test_port_a"]["initial_capital"] == 2000.0
    assert ports["test_port_b"]["initial_capital"] == 5000.0

def test_portfolio_isolation_and_metrics():
    # Setup Portfolios
    client.post("/api/portfolios", json={
        "id": "test_port_a",
        "name": "Portfolio A",
        "initial_capital": 1000.0,
        "risk_per_trade_percent": 1.0
    })
    client.post("/api/portfolios", json={
        "id": "test_port_b",
        "name": "Portfolio B",
        "initial_capital": 500.0,
        "risk_per_trade_percent": 2.0
    })

    # Add trades to Port A (2 Wins, 1 Loss)
    # Win 1: +2.5 R ($25.0)
    client.post("/api/portfolios/test_port_a/trades", json={
        "trade_date": "2026-01-10",
        "symbol": "XAUUSD",
        "direction": "BUY",
        "risk_usd": 10.0,
        "total_pnl": 25.0,
        "r_multiple": 2.5,
        "setup": "Breakout",
        "outcome": "W"
    })
    # Win 2: +1.5 R ($15.0)
    client.post("/api/portfolios/test_port_a/trades", json={
        "trade_date": "2026-01-12",
        "symbol": "EURUSD",
        "direction": "SELL",
        "risk_usd": 10.0,
        "total_pnl": 15.0,
        "r_multiple": 1.5,
        "setup": "Breakout",
        "outcome": "W"
    })
    # Loss 1: -1.0 R (-$10.0)
    client.post("/api/portfolios/test_port_a/trades", json={
        "trade_date": "2026-02-05",
        "symbol": "XAUUSD",
        "direction": "BUY",
        "risk_usd": 10.0,
        "total_pnl": -10.0,
        "r_multiple": -1.0,
        "setup": "Pullback",
        "outcome": "L"
    })

    # Add trade to Port B (1 Big Loss: -2.0 R, -$20.0)
    client.post("/api/portfolios/test_port_b/trades", json={
        "trade_date": "2026-01-15",
        "symbol": "BTCUSD",
        "direction": "BUY",
        "risk_usd": 10.0,
        "total_pnl": -20.0,
        "r_multiple": -2.0,
        "setup": "Fibo",
        "outcome": "L"
    })

    # ----------------- VERIFY PORTFOLIO A -----------------
    res_a = client.get("/api/portfolios/test_port_a/dashboard")
    assert res_a.status_code == 200
    dash_a = res_a.json()
    kpi_a = dash_a["kpi"]

    # Port A stats:
    # Trades = 3 (2 W, 1 L)
    assert kpi_a["total_trades"] == 3
    assert kpi_a["win_count"] == 2
    assert kpi_a["loss_count"] == 1
    # Win rate = 2 / 3 = 66.7%
    assert kpi_a["win_rate"] == 66.7
    # Total P/L = 25 + 15 - 10 = $30.0
    assert kpi_a["total_pnl"] == 30.0
    # Balance = 1000 + 30 = $1030.0
    assert kpi_a["current_balance"] == 1030.0
    # Total R = 2.5 + 1.5 - 1.0 = +3.0 R
    assert kpi_a["total_r"] == 3.0
    # Avg win R = (2.5 + 1.5) / 2 = 2.0 R
    assert kpi_a["avg_win_r"] == 2.0
    # Avg loss R = -1.0 R
    assert kpi_a["avg_loss_r"] == -1.0

    # Quick stats Port A
    assert dash_a["quick_stats"]["best_trade_r"] == 2.5
    assert dash_a["quick_stats"]["worst_trade_r"] == -1.0

    # Monthly performance Port A (Jan has 4.0 R, Feb has -1.0 R)
    m_jan = next(m for m in dash_a["monthly_performance"] if m["month"] == 1)
    m_feb = next(m for m in dash_a["monthly_performance"] if m["month"] == 2)
    assert m_jan["total_r"] == 4.0
    assert m_jan["trades"] == 2
    assert m_feb["total_r"] == -1.0
    assert m_feb["trades"] == 1

    # Calendar Heatmap Port A
    assert "2026-01-10" in dash_a["calendar_daily"]
    assert dash_a["calendar_daily"]["2026-01-10"]["total_r"] == 2.5
    # Port B's trade on 2026-01-15 MUST NOT be in Port A's calendar!
    assert "2026-01-15" not in dash_a["calendar_daily"]

    # ----------------- VERIFY PORTFOLIO B ISOLATION -----------------
    res_b = client.get("/api/portfolios/test_port_b/dashboard")
    assert res_b.status_code == 200
    dash_b = res_b.json()
    kpi_b = dash_b["kpi"]

    # Port B stats: exactly 1 trade, 0 Wins, 1 Loss
    assert kpi_b["total_trades"] == 1
    assert kpi_b["win_count"] == 0
    assert kpi_b["loss_count"] == 1
    assert kpi_b["win_rate"] == 0.0
    assert kpi_b["total_pnl"] == -20.0
    assert kpi_b["current_balance"] == 480.0 # 500 - 20
    assert kpi_b["total_r"] == -2.0

    # Calendar Port B has only 2026-01-15
    assert "2026-01-15" in dash_b["calendar_daily"]
    assert dash_b["calendar_daily"]["2026-01-15"]["total_r"] == -2.0
    # None of Port A's dates should appear
    assert "2026-01-10" not in dash_b["calendar_daily"]
    assert "2026-02-05" not in dash_b["calendar_daily"]

def test_trade_filtering_and_deletion():
    client.post("/api/portfolios", json={
        "id": "test_port_a",
        "name": "Portfolio A",
        "initial_capital": 1000.0
    })

    t1 = client.post("/api/portfolios/test_port_a/trades", json={
        "trade_date": "2026-01-01",
        "symbol": "BTCUSD",
        "direction": "BUY",
        "risk_usd": 10.0,
        "total_pnl": 30.0,
        "r_multiple": 3.0,
        "setup": "Breakout",
        "outcome": "W"
    }).json()

    t2 = client.post("/api/portfolios/test_port_a/trades", json={
        "trade_date": "2026-01-02",
        "symbol": "XAUUSD",
        "direction": "SELL",
        "risk_usd": 10.0,
        "total_pnl": -10.0,
        "r_multiple": -1.0,
        "setup": "Pullback",
        "outcome": "L"
    }).json()

    # Filter by symbol
    res_btc = client.get("/api/portfolios/test_port_a/trades?symbol=BTCUSD").json()
    assert len(res_btc["trades"]) == 1
    assert res_btc["trades"][0]["symbol"] == "BTCUSD"

    # Filter by outcome
    res_w = client.get("/api/portfolios/test_port_a/trades?outcome=W").json()
    assert len(res_w["trades"]) == 1
    assert res_w["trades"][0]["outcome"] == "W"

    # Delete trade t2
    del_res = client.delete(f"/api/portfolios/test_port_a/trades/{t2['trade_id']}")
    assert del_res.status_code == 200

    # Verify only 1 trade remains
    dash = client.get("/api/portfolios/test_port_a/dashboard").json()
    assert dash["kpi"]["total_trades"] == 1
    assert dash["kpi"]["total_r"] == 3.0
