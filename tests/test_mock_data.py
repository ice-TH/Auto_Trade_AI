from src.data.mock_adapter import MockDataAdapter
from src.data.base import TimeFrame, DataStatus

def test_mock_data_symbols():
    adapter = MockDataAdapter()
    symbols = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
    for sym in symbols:
        assert sym in adapter.symbols_config
        day_bars = adapter.get_bars(sym, TimeFrame.DAY, limit=50)
        assert len(day_bars) > 0
        assert day_bars[0].status == DataStatus.SIMULATION
        assert day_bars[0].symbol == sym

def test_googl_separation():
    adapter = MockDataAdapter()
    # GOOGL must exist, GOOG must not be in default configured symbols
    assert "GOOGL" in adapter.symbols_config
    assert "GOOG" not in adapter.symbols_config
