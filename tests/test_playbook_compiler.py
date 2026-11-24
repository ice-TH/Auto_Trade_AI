import pytest
from pathlib import Path
from src.analysis.playbook_compiler import compile_playbook, get_asset_playbook
from src.analysis.trade_reviewer import get_playbook_content

def test_compile_playbook_produces_unified_file(tmp_path):
    output_file = tmp_path / "test_playbook.md"
    content = compile_playbook(output_file)

    assert output_file.exists()
    assert "Antigravity Active Trading Playbook (Master Unified View)" in content
    assert "Table of Contents" in content
    # Check that all sub-playbooks are merged
    assert "CORE-RULE-01" in content
    assert "XAU-RULE-01" in content
    assert "BTC-RULE-00" in content
    assert "EQ-RULE-01" in content

def test_get_asset_playbook_isolates_context():
    # Gold query
    gold_pb = get_asset_playbook("XAUUSD")
    assert "CORE-RULE-01" in gold_pb
    assert "XAU-RULE-05" in gold_pb
    assert "BTC-RULE-00" not in gold_pb
    assert "EQ-RULE-01" not in gold_pb

    # BTC query
    btc_pb = get_asset_playbook("BTCUSDm")
    assert "CORE-RULE-01" in btc_pb
    assert "BTC-RULE-00" in btc_pb
    assert "XAU-RULE-05" not in btc_pb
    assert "EQ-RULE-01" not in btc_pb

    # Equities query
    nvda_pb = get_asset_playbook("NVDA")
    assert "CORE-RULE-01" in nvda_pb
    assert "EQ-RULE-01" in nvda_pb
    assert "XAU-RULE-05" not in nvda_pb

def test_trade_reviewer_returns_compiled_playbook():
    content = get_playbook_content()
    assert len(content) > 500
    assert "CORE-RULE" in content
    assert "XAU-RULE" in content
