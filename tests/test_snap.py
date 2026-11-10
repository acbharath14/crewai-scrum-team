"""Tests for the Fibonacci snap in advisory estimation.

LLM estimators do not stay on the Fibonacci scale: a real run
produced 10 and 12. The deterministic builder snaps those to the
nearest step instead of stopping the sprint, and records the
original values so the change is auditable.
"""

import pytest

from scrum_crew.pipeline import advisory_lock, snap_to_fibonacci


def test_snap_keeps_fibonacci_values():
    assert snap_to_fibonacci(8) == 8
    assert snap_to_fibonacci(13) == 13


def test_snap_10_goes_to_8_and_12_goes_to_13():
    assert snap_to_fibonacci(10) == 8
    assert snap_to_fibonacci(12) == 13


def test_snap_tie_goes_to_lower_step():
    # 4 is equidistant from 3 and 5; lower step wins.
    assert snap_to_fibonacci(4) == 3


@pytest.mark.parametrize(
    "developer,sdet,analyst,locked,snapped_estimates,snapped_from",
    [
        # Tropical ST003: developer 8, sdet 13, analyst 10.
        (8, 13, 10, 8,
         {"developer": 8, "sdet": 13, "analyst": 8},
         {"analyst": 10}),
        # Tropical ST004: developer 13, sdet 10, analyst 12.
        (13, 10, 12, 13,
         {"developer": 13, "sdet": 8, "analyst": 13},
         {"sdet": 10, "analyst": 12}),
    ],
)
def test_advisory_lock_snaps_and_records_original(
        developer, sdet, analyst, locked, snapped_estimates, snapped_from):
    result = advisory_lock(developer, sdet, analyst)
    assert result["locked"] == locked
    assert result["estimates"] == snapped_estimates
    assert result["snapped_from"] == snapped_from


def test_advisory_lock_for_5_8_8_is_8_not_null():
    result = advisory_lock(5, 8, 8)
    assert result["locked"] == 8
    assert result["spread_steps"] == 1
    assert result["spread_points"] == 3
    assert result["snapped_from"] == {}
