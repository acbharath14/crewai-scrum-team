"""Tests for the deterministic sprint closure audit.

A sprint review that only summarizes is not closure. Closure must
check every deliverable: criterion coverage, code per story, test
file per story, notes listing code files, review naming stories,
sign-off naming sprint and backlog.
"""

import json
from pathlib import Path

from scrum_crew.run import (
    ROOT,
    _validate_closure,
    _write_backlog_doc,
    _write_closure_audit,
    _write_delivery_doc,
)


def _setup(tmp_path, root):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "requirement.md").write_text("Build widget.", encoding="utf-8")
    (outputs / "epic.md").write_text("Widget epic.", encoding="utf-8")
    (outputs / "sprint.json").write_text(json.dumps({"sprint": []}),
                                         encoding="utf-8")
    (outputs / "stories.json").write_text(json.dumps({"stories": [{
        "id": "STORY-1", "title": "Widget",
        "acceptance_criteria": [{"id": "AC-1.1", "text": "It works."}],
        "dependencies": [], "risks": [], "testable": True}]}),
        encoding="utf-8")
    (outputs / "run_manifest.json").write_text("{}", encoding="utf-8")
    (outputs / "implementation_notes.md").write_text(
        "STORY-1 implemented in demo_app/server.py", encoding="utf-8")
    (outputs / "tests_map.json").write_text(
        "STORY-1 AC-1.1 tests/test_story-1.py", encoding="utf-8")
    (outputs / "deploy_smoke.md").write_text(
        "STORY-1 server started, smoke PASS", encoding="utf-8")
    (outputs / "validation_report.md").write_text(
        "AC-1.1 PASS tests/test_story-1.py", encoding="utf-8")
    (outputs / "rework_log.md").write_text("No rework.", encoding="utf-8")
    (outputs / "review.md").write_text(
        "STORY-1 reviewed: epic, stories, sprint, tests_map, "
        "implementation_notes, deploy_smoke, validation_report.",
        encoding="utf-8")
    (outputs / "retrospective.md").write_text(
        "Action: fix docs, owner: Scrum Master.", encoding="utf-8")
    (outputs / "signoff.md").write_text(
        "STORY-1 accepted. Backlog: STORY-2.", encoding="utf-8")
    code_dir = root / "demo_app"
    code_dir.mkdir(exist_ok=True)
    (code_dir / "server.py").write_text(
        "# STORY-1\nx = 1\n", encoding="utf-8")
    tests_dir = root / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_story-1.py").write_text(
        "def test_widget():\n    assert 'STORY-1' or 'AC-1.1'\n",
        encoding="utf-8")
    return outputs


def test_closure_passes_for_complete_sprint(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outputs = _setup(tmp_path, root)
    sprint = [{"id": "STORY-1", "title": "Widget", "locked": 5}]
    backlog = [{"id": "STORY-2", "title": "Gadget", "reasons": ["not ready"]}]
    errors, checklist = _validate_closure(
        sprint, backlog, outputs, "demo_app",
        ["demo_app/server.py", "tests/test_story-1.py"], root=root)
    assert errors == [], errors
    assert any(name == "validation covers AC-1.1" and ok
               for name, ok, _d in checklist)


def test_closure_fails_for_missing_criterion(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outputs = _setup(tmp_path, root)
    (outputs / "validation_report.md").write_text(
        "No criteria here.", encoding="utf-8")
    errors, _c = _validate_closure(
        [{"id": "STORY-1"}], [], outputs, "demo_app",
        ["demo_app/server.py", "tests/test_story-1.py"], root=root)
    assert any("AC-1.1" in e for e in errors)


def test_closure_fails_for_missing_test_file(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outputs = _setup(tmp_path, root)
    (root / "tests" / "test_story-1.py").unlink()
    errors, _c = _validate_closure(
        [{"id": "STORY-1"}], [], outputs, "demo_app",
        ["demo_app/server.py"], root=root)
    assert any("test_story-1.py" in e for e in errors)


def test_closure_fails_for_root_only_code(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outputs = _setup(tmp_path, root)
    errors, _c = _validate_closure(
        [{"id": "STORY-1"}], [], outputs, "demo_app",
        ["user.py", "tests/test_story-1.py"], root=root)
    assert any("no Phase 2 code file cites STORY-1" in e or
               "demo_app/server.py" in e for e in errors)


def test_backlog_and_delivery_docs(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    _write_backlog_doc(outputs, [{"id": "STORY-2", "title": "Gadget",
                                  "reasons": ["not ready"]}])
    doc = (outputs / "backlog.md").read_text(encoding="utf-8")
    assert "STORY-2" in doc and "not ready" in doc
    _write_closure_audit(outputs, [("epic.md present", True, "")])
    assert "PASS" in (outputs / "closure_audit.md").read_text(encoding="utf-8")
    _write_delivery_doc(
        outputs, [{"id": "STORY-1", "title": "Widget", "locked": 5}],
        [{"id": "STORY-2", "title": "Gadget"}],
        ["demo_app/server.py"], True,
        [("epic.md present", True, "")])
    delivery = (outputs / "delivery.md").read_text(encoding="utf-8")
    assert "Closure audit" in delivery
    assert "backlog.md" in delivery
