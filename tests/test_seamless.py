"""Tests for the seamless patch: advisory estimation, sprint.json,
output validation, and backend preflight.

Estimation is advisory only in the real crew path: a story with
estimates [5, 8, 8] locks at 8, not null, and DoR does not fail it
for points. A task counts as done only when its file exists.
"""

import json

import sys

from scrum_crew.pipeline import advisory_lock, dor_check_advisory
from scrum_crew.run import (
    _build_sprint_json,
    _estimate_value,
    _run_test_suite,
    _validate_outputs,
)


def story():
    return {
        "id": "STORY-5",
        "title": "Example story",
        "description": "As a user I can do something.",
        "acceptance_criteria": [{"id": "AC-5.1", "text": "It works."}],
        "dependencies": [],
        "risks": [],
        "testable": True,
    }


def test_advisory_lock_for_5_8_8_is_8_not_null():
    result = advisory_lock(5, 8, 8)
    assert result["locked"] == 8
    assert result["spread_steps"] == 1
    assert result["spread_points"] == 3


def test_advisory_dor_does_not_fail_for_points():
    assert dor_check_advisory(story(), locked_estimate=None)["passed"] is True
    result = dor_check_advisory(story(), locked_estimate=13)
    assert result["passed"] is True
    assert result["warnings"]


def test_advisory_dor_still_fails_for_missing_criteria():
    broken = story()
    broken["acceptance_criteria"] = []
    assert dor_check_advisory(broken, locked_estimate=5)["passed"] is False


def test_estimate_value_handles_both_formats():
    assert _estimate_value(5) == 5
    assert _estimate_value({"points": 8, "rationale": "x"}) == 8
    assert _estimate_value({"rationale": "x"}) is None
    assert _estimate_value("5") is None


def _write_phase1(tmp_path):
    (tmp_path / "stories.json").write_text(
        json.dumps({"stories": [story()]}), encoding="utf-8")
    for role in ("developer", "sdet", "analyst"):
        (tmp_path / f"estimates_{role}.json").write_text(
            json.dumps({"STORY-5": {"points": 5 if role == "developer" else 8,
                                     "rationale": "x"}}),
            encoding="utf-8")


def test_build_sprint_json_locks_story_5_at_8(tmp_path):
    _write_phase1(tmp_path)
    sprint, backlog, errors = _build_sprint_json(tmp_path)
    assert errors == []
    assert [s["id"] for s in sprint] == ["STORY-5"]
    assert sprint[0]["locked"] == 8
    assert backlog == []
    doc = json.loads((tmp_path / "sprint.json").read_text(encoding="utf-8"))
    assert doc["sprint"][0]["locked"] == 8


def test_build_sprint_json_fails_when_estimate_missing(tmp_path):
    _write_phase1(tmp_path)
    (tmp_path / "estimates_sdet.json").unlink()
    sprint, backlog, errors = _build_sprint_json(tmp_path)
    assert sprint == [] and backlog == []
    assert errors
    assert not (tmp_path / "sprint.json").exists()


def test_run_test_suite_passes_and_fails(tmp_path):
    ok_dir = tmp_path / "ok"
    ok_dir.mkdir()
    (ok_dir / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    ok, _tail = _run_test_suite(path=str(ok_dir), python=sys.executable)
    assert ok is True
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    (bad_dir / "test_bad.py").write_text(
        "def test_bad():\n    assert False\n", encoding="utf-8")
    ok, tail = _run_test_suite(path=str(bad_dir), python=sys.executable)
    assert ok is False
    assert "test_bad" in tail


def test_validate_outputs_names_missing_file(tmp_path):
    errors = _validate_outputs(
        tmp_path, {"po_signoff": ("signoff.md", "Product Owner")})
    assert errors == ["po_signoff (Product Owner): missing signoff.md"]
    (tmp_path / "signoff.md").write_text("ok", encoding="utf-8")
    assert _validate_outputs(
        tmp_path, {"po_signoff": ("signoff.md", "Product Owner")}) == []
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    errors = _validate_outputs(
        tmp_path, {"bad_task": ("bad.json", "SDET")})
    assert errors and "invalid JSON" in errors[0]
