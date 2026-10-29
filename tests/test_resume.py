"""Tests for --resume mode.

Resume must not archive or re-run Phase 1, and must refuse when
the requirement or target changed since Phase 1, because Phase 2
on stale stories is not a defined run.
"""

import hashlib
import json

from scrum_crew.run import _check_resume, _write_run_manifest


def _manifest(tmp_path, requirement_text, target):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    _write_run_manifest(outputs, "requirements.md", requirement_text,
                        target, True)
    return outputs


def test_resume_allows_same_requirement_and_target(tmp_path):
    outputs = _manifest(tmp_path, "Build widget.", "demo_app")
    assert _check_resume(outputs, "Build widget.", "demo_app") == []


def test_resume_refuses_changed_requirement(tmp_path):
    outputs = _manifest(tmp_path, "Build widget.", "demo_app")
    errors = _check_resume(outputs, "Build gadget instead.", "demo_app")
    assert errors and "changed" in errors[0]


def test_resume_refuses_changed_target(tmp_path):
    outputs = _manifest(tmp_path, "Build widget.", "demo_app")
    errors = _check_resume(outputs, "Build widget.", "tropical_delight")
    assert errors and "target" in errors[0].lower()


def test_resume_refuses_missing_manifest(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    errors = _check_resume(outputs, "Build widget.", "demo_app")
    assert errors and "manifest" in errors[0].lower()


def test_manifest_sha_matches_requirement_text(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    manifest = _write_run_manifest(outputs, "requirements.md",
                                   "Build widget.", "demo_app", True)
    assert manifest["requirement_sha256"] == hashlib.sha256(
        "Build widget.".encode("utf-8")).hexdigest()
    stored = json.loads((outputs / "run_manifest.json").read_text(
        encoding="utf-8"))
    assert stored["requirement_sha256"] == manifest["requirement_sha256"]
