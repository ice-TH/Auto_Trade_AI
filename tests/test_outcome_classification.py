"""Unit tests for unified Breakeven (BE) outcome classification."""

import pytest
from src.execution.mt5_journal_sync import (
    BE_R_THRESHOLD,
    classify_trade_outcome,
    outcome_to_long_label,
)


@pytest.mark.parametrize(
    "r_multiple,expected",
    [
        (0.0, "BE"),
        (0.05, "BE"),
        (0.10, "BE"),
        (0.20, "BE"),
        (-0.05, "BE"),
        (-0.15, "BE"),
        (-0.20, "BE"),
        (0.21, "W"),
        (1.5, "W"),
        (-0.21, "L"),
        (-1.0, "L"),
    ],
)
def test_classify_trade_outcome(r_multiple: float, expected: str):
    assert BE_R_THRESHOLD == 0.20
    assert classify_trade_outcome(r_multiple) == expected


@pytest.mark.parametrize(
    "short_code,expected_long",
    [
        ("W", "WIN"),
        ("L", "LOSS"),
        ("BE", "BREAKEVEN"),
        ("w", "WIN"),
        ("unknown", "BREAKEVEN"),
    ],
)
def test_outcome_to_long_label(short_code: str, expected_long: str):
    assert outcome_to_long_label(short_code) == expected_long
