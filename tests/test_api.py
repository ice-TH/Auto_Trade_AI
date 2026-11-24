from starlette.testclient import TestClient
from src.web.app import app

client = TestClient(app)

def test_get_status():
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "HEALTHY"
    assert data["trading_mode"] in ["READ_ONLY", "LIVE"]
    assert data["risk_profile"]["base_capital_thb"] > 0.0
    assert data["risk_profile"]["max_leverage"] == 5.0

def test_get_symbols():
    res = client.get("/api/symbols")
    assert res.status_code == 200
    data = res.json()
    assert "GOOGL" in data["symbols"]
    assert "AAPL" in data["symbols"]

def test_get_bars_and_indicators():
    # Test XAUUSD (available on live broker) or AAPL
    res = client.get("/api/market/bars/XAUUSD?timeframe=1D&limit=50")
    if res.status_code != 200 or len(res.json().get("bars", [])) == 0:
        res = client.get("/api/market/bars/AAPL?timeframe=1D&limit=50")
    assert res.status_code == 200
    data = res.json()
    assert len(data["bars"]) > 0
    assert "ema15" in data["indicators"]
    assert "atr14" in data["indicators"]

def test_get_zones():
    res = client.get("/api/zones/AAPL")
    assert res.status_code == 200
    data = res.json()
    assert "auto_sr_zones" in data
    assert "manual_zones" in data

def test_manual_zone_crud():
    payload = {
        "symbol": "AAPL",
        "timeframe": "1D",
        "price_high": 235.0,
        "price_low": 230.0,
        "label": "Test Daily Support",
        "zone_type": "SUPPORT",
        "is_locked": False
    }
    create_res = client.post("/api/zones/manual", json=payload)
    assert create_res.status_code == 200
    zone_id = create_res.json()["zone_id"]

    # Toggle lock
    lock_res = client.patch(f"/api/zones/manual/{zone_id}/lock")
    assert lock_res.status_code == 200
    assert lock_res.json()["is_locked"] is True

    # Try deleting locked zone (should fail with 400)
    del_fail = client.delete(f"/api/zones/manual/{zone_id}")
    assert del_fail.status_code == 400

    # Unlock and delete
    client.patch(f"/api/zones/manual/{zone_id}/lock")
    del_ok = client.delete(f"/api/zones/manual/{zone_id}")
    assert del_ok.status_code == 200

def test_capture_screenshot():
    payload = {
        "symbol": "AAPL",
        "timeframe": "1D",
        "event_id": "TEST_CAPTURE",
        "notes": "Automated unit test capture"
    }
    res = client.post("/api/capture", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "CAPTURED"
    assert "relative_path" in data["metadata"]
