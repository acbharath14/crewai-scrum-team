"""Tests for scrum_crew.pipeline (no CrewAI, no Ollama needed)."""

import pytest

from scrum_crew.pipeline import (
    FIBONACCI,
    MAX_READY_POINTS,
    MAX_REWORK_ROUNDS,
    build_traceability,
    converge_estimates,
    dod_check,
    dor_check,
    next_step_after_failure,
    triage_new_requirement,
    validate_epic,
    validate_story,
)


def story(**overrides):
    base = {
        "id": "STORY-1",
        "title": "Create task",
        "description": "As a user I can create a task.",
        "acceptance_criteria": [{"id": "AC-1.1", "text": "POST returns 201"}],
        "dependencies": [],
        "risks": [],
        "testable": True,
    }
    base.update(overrides)
    return base


# -- estimation convergence ----------------------------------------------

def test_converged_estimates_lock_to_median():
    result = converge_estimates(5, 5, 3)
    assert result["divergent"] is False
    assert result["spread_steps"] == 1
    assert result["locked"] == 5


def test_one_step_spread_is_not_divergence():
    result = converge_estimates(3, 3, 5)
    assert result["divergent"] is False
    assert result["locked"] == 3


def test_two_step_spread_is_divergence():
    result = converge_estimates(8, 3, 5)
    assert result["divergent"] is True
    assert result["spread_steps"] == 2
    assert result["locked"] is None


def test_non_fibonacci_estimate_rejected():
    with pytest.raises(ValueError):
        converge_estimates(4, 3, 5)


# -- schema validation ----------------------------------------------------

def test_valid_epic_and_story_pass():
    assert validate_epic({"id": "EPIC-1", "title": "T",
                          "business_goal": "G"}) == []
    assert validate_story(story()) == []


def test_story_missing_criteria_and_dependencies_flagged():
    errors = validate_story(story(acceptance_criteria=[]))
    assert any("acceptance criteria" in e for e in errors)
    broken = story()
    del broken["dependencies"]
    assert any("dependencies" in e for e in validate_story(broken))


# -- Definition of Ready ---------------------------------------------------

def test_dor_passes_for_ready_story():
    assert dor_check(story(), locked_estimate=5)["passed"] is True


def test_dor_fails_without_locked_estimate():
    result = dor_check(story(), locked_estimate=None)
    assert result["passed"] is False
    assert any("locked estimate" in m for m in result["missing"])


def test_dor_fails_for_oversized_story():
    result = dor_check(story(), locked_estimate=13)
    assert result["passed"] is False
    assert any("split" in m for m in result["missing"])


def test_dor_boundary_at_max_ready_points():
    assert dor_check(story(), locked_estimate=MAX_READY_POINTS)["passed"]


def test_dor_fails_when_not_testable():
    result = dor_check(story(testable=False), locked_estimate=3)
    assert result["passed"] is False


# -- Definition of Done -----------------------------------------------------

def full_evidence():
    return {"code_refs": ["STORY-1"], "tests_passing": True,
            "criteria_validated": True, "deployed_smoke": True,
            "docs_updated": True}


def test_dod_passes_with_full_evidence():
    assert dod_check("STORY-1", full_evidence())["passed"] is True


def test_dod_lists_every_missing_item():
    evidence = full_evidence()
    evidence["deployed_smoke"] = False
    evidence["docs_updated"] = False
    result = dod_check("STORY-1", evidence)
    assert result["passed"] is False
    assert len(result["missing"]) == 2


# -- traceability matrix ------------------------------------------------------

def test_matrix_pass_requires_all_mapped_tests_green():
    criteria = [{"id": "AC-1.1", "text": "POST returns 201"}]
    matrix = build_traceability(criteria, {"t1": "PASS"},
                                {"AC-1.1": ["t1"]})
    assert matrix["overall"] == "PASS"
    assert matrix["rows"][0]["verdict"] == "PASS"


def test_matrix_fail_on_any_failed_test():
    criteria = [{"id": "AC-1.1", "text": "POST returns 201"}]
    matrix = build_traceability(criteria, {"t1": "PASS", "t2": "FAIL"},
                                {"AC-1.1": ["t1", "t2"]})
    assert matrix["overall"] == "FAIL"
    assert matrix["rows"][0]["verdict"] == "FAIL"


def test_matrix_uncovered_criterion_is_not_a_pass():
    criteria = [{"id": "AC-9.9", "text": "Untested rule"}]
    matrix = build_traceability(criteria, {}, {})
    assert matrix["rows"][0]["verdict"] == "UNCOVERED"
    assert matrix["overall"] == "FAIL"


def test_matrix_not_run_when_test_missing_from_results():
    criteria = [{"id": "AC-1.1", "text": "POST returns 201"}]
    matrix = build_traceability(criteria, {}, {"AC-1.1": ["t1"]})
    assert matrix["rows"][0]["verdict"] == "NOT-RUN"


# -- rework cap and scope control ----------------------------------------------

def test_rework_capped_at_two_rounds_then_escalates():
    assert next_step_after_failure(0) == ("rework", 1)
    assert next_step_after_failure(1) == ("rework", 2)
    assert next_step_after_failure(2) == ("escalate", None)
    assert next_step_after_failure(3) == ("escalate", None)
    assert MAX_REWORK_ROUNDS == 2


def test_mid_sprint_discovery_goes_to_backlog():
    assert triage_new_requirement(sprint_active=True) == "backlog"
    assert triage_new_requirement(sprint_active=False) == "sprint_candidate"
