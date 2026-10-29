"""Tests for the defined-setup builder.

A real run must start from a requirement file, build only in the
target directory, and document each phase. An invented epic, a
lone file at the repo root, or terminal-only Phase 2 output must
not count as delivery.
"""

import json
from pathlib import Path

import pytest

from scrum_crew.crew import build_execution_crew, build_planning_crew
from scrum_crew.run import (
    ROOT,
    _archive_previous_outputs,
    _load_requirement,
    _resolve_target,
    _validate_delivery,
    _write_delivery_doc,
    _write_run_manifest,
)


def test_load_requirement_rejects_empty(tmp_path):
    empty = tmp_path / "req.md"
    empty.write_text("  \n", encoding="utf-8")
    with pytest.raises(ValueError):
        _load_requirement(empty)
    with pytest.raises(OSError):
        _load_requirement(tmp_path / "missing.md")


def test_resolve_target_must_be_inside_repo():
    assert _resolve_target("demo_app").name == "demo_app"
    with pytest.raises(ValueError):
        _resolve_target("../outside")
    with pytest.raises(ValueError):
        _resolve_target("does-not-exist-dir")


def test_planning_crew_injects_requirement_verbatim():
    crew = build_planning_crew(requirement_text="Build a widget board.")
    assert "Build a widget board." in crew.tasks[0].description
    assert "do not invent" in crew.tasks[0].description.lower()


def test_execution_crew_injects_target():
    crew = build_execution_crew(target_dir="demo_app")
    by_name = {task.description: task for task in crew.tasks}
    descriptions = " ".join(task.description for task in crew.tasks)
    assert "Implement ONLY in demo_app/" in descriptions
    assert "tests/test_<story-id-lowercase>.py" in descriptions


def _delivery_setup(tmp_path, writes):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "implementation_notes.md").write_text(
        "Implemented STORY-1 in demo_app/server.py", encoding="utf-8")
    (outputs / "tests_map.json").write_text(
        json.dumps({"STORY-1": ["tests/test_story-1.py"]}),
        encoding="utf-8")
    log = outputs / "tool-calls.log"
    log.write_text("".join(
        f"2026-10-28 20:00:00 write {ROOT / w} (10 bytes)\n"
        for w in writes), encoding="utf-8")
    return outputs


def test_validate_delivery_passes_for_target_and_tests(tmp_path):
    outputs = _delivery_setup(
        tmp_path, ["demo_app/server.py", "tests/test_story-1.py"])
    errors, writes = _validate_delivery(
        [{"id": "STORY-1"}], outputs, "demo_app", 0, root=ROOT)
    assert errors == []
    assert "demo_app/server.py" in writes
    assert "tests/test_story-1.py" in writes


def test_validate_delivery_fails_for_root_only_code(tmp_path):
    outputs = _delivery_setup(
        tmp_path, ["user.py", "tests/test_story-1.py"])
    errors, _writes = _validate_delivery(
        [{"id": "STORY-1"}], outputs, "demo_app", 0, root=ROOT)
    assert any("no code write to demo_app/" in e for e in errors)


def test_validate_delivery_fails_when_story_missing_from_notes(tmp_path):
    outputs = _delivery_setup(
        tmp_path, ["demo_app/server.py", "tests/test_story-1.py"])
    (outputs / "implementation_notes.md").write_text(
        "Implemented something, no story id.", encoding="utf-8")
    errors, _writes = _validate_delivery(
        [{"id": "STORY-1"}], outputs, "demo_app", 0, root=ROOT)
    assert any("STORY-1" in e for e in errors)


def test_archive_previous_outputs(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "epic.md").write_text("old", encoding="utf-8")
    archived = _archive_previous_outputs(outputs, root=tmp_path)
    assert archived is not None
    assert not outputs.exists()
    assert (archived / "epic.md").read_text(encoding="utf-8") == "old"
    assert _archive_previous_outputs(tmp_path / "nope", root=tmp_path) is None


def test_run_manifest_and_delivery_doc(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    manifest = _write_run_manifest(
        outputs, "requirements.md", "Build a widget board.",
        "demo_app", True)
    assert manifest["requirement_sha256"]
    assert manifest["target"] == "demo_app"
    assert manifest["backend"] in ("ollama", "llama-server")
    _write_delivery_doc(
        outputs, [{"id": "STORY-1", "title": "Widget", "locked": 5}],
        [{"id": "STORY-2", "title": "Gadget"}],
        ["demo_app/server.py", "tests/test_story-1.py"], True)
    doc = (outputs / "delivery.md").read_text(encoding="utf-8")
    assert "STORY-1" in doc
    assert "demo_app/server.py" in doc
    assert "Test suite gate: PASS" in doc
