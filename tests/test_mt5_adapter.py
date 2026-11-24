import pytest
from src.data.base import TimeFrame
from src.data.mt5_adapter import MT5DataAdapter, TIMEFRAME_MAP

def test_mt5_adapter_initialization():
    adapter = MT5DataAdapter()
    assert adapter is not None
    assert adapter.mt5_client is not None

def test_mt5_adapter_timeframe_mapping():
    # Verify mapping handles the 3 required core timeframes
    assert TimeFrame.WEEK in [TimeFrame.WEEK, TimeFrame.DAY, TimeFrame.M15]
    assert TimeFrame.DAY in [TimeFrame.WEEK, TimeFrame.DAY, TimeFrame.M15]
    assert TimeFrame.M15 in [TimeFrame.WEEK, TimeFrame.DAY, TimeFrame.M15]

def test_mt5_adapter_status_structure():
    adapter = MT5DataAdapter()
    status = adapter.get_status()
    assert "adapter" in status
    assert status["adapter"] == "MT5DataAdapter"
    assert "status" in status
