"""Tests for the Fibonacci snap in advisory estimation.

LLM estimators do not stay on the Fibonacci scale: a real run
produced 10 and 12. The deterministic builder snaps those to the
nearest step instead of stopping the sprint, and records the
original values so the change is auditable.
"""

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


def test_advisory_lock_snaps_st003_and_records_original():
    # Tropical ST003: developer 8, sdet 13, analyst 10.
    result = advisory_lock(8, 13, 10)
    assert result["locked"] == 8
    assert result["estimates"] == {"developer": 8, "sdet": 13,
                                   "analyst": 8}
    assert result["snapped_from"] == {"analyst": 10}


def test_advisory_lock_snaps_st004_and_records_originals():
    # Tropical ST004: developer 13, sdet 10, analyst 12.
    result = advisory_lock(13, 10, 12)
    assert result["locked"] == 13
    assert result["estimates"] == {"developer": 13, "sdet": 8,
                                   "analyst": 13}
    assert result["snapped_from"] == {"sdet": 10, "analyst": 12}


def test_advisory_lock_clean_values_have_empty_snapped_from():
    result = advisory_lock(5, 8, 8)
    assert result["locked"] == 8
    assert result["snapped_from"] == {}
