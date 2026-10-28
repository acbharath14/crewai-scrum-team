"""Tests for task-level progress reporting (stdlib only, except wiring).

PhaseProgress is pure stdlib so these tests run anywhere pytest does.
The crew-wiring test is guarded by importorskip: it only runs where
CrewAI is installed, and it pins the wiring to CrewAI 1.15.30's
_set_tasks_callbacks kickoff-prep behavior.
"""

import re

import pytest

from scrum_crew.run import PhaseProgress, _fmt_elapsed

PLAN = [("define_epic", "Product Owner"),
        ("break_down_stories", "Business Analyst")]


def test_fmt_elapsed():
    assert _fmt_elapsed(0) == "0m00s"
    assert _fmt_elapsed(42) == "0m42s"
    assert _fmt_elapsed(65) == "1m05s"
    assert _fmt_elapsed(3723) == "62m03s"


def test_start_prints_numbered_plan(capsys):
    progress = PhaseProgress("Phase 1", PLAN, "/nonexistent/progress.log")
    progress.start()
    out = capsys.readouterr().out
    assert "1. define_epic (Product Owner)" in out
    assert "2. break_down_stories (Business Analyst)" in out


def test_callback_lines_and_next_task(capsys):
    progress = PhaseProgress("Phase 1", PLAN, "/nonexistent/progress.log")
    progress.start()
    capsys.readouterr()
    progress(None)
    out = capsys.readouterr().out
    assert re.search(r"\[1/2\] define_epic done -- Product Owner, \d+m\d\ds "
                     r"-> next: break_down_stories", out)
    progress(None)
    out = capsys.readouterr().out
    assert re.search(r"\[2/2\] break_down_stories done -- Business Analyst, "
                     r"\d+m\d\ds -> phase done", out)


def test_callback_ignores_calls_after_plan_exhausted(capsys):
    progress = PhaseProgress("Phase 1", PLAN, "/nonexistent/progress.log")
    progress.start()
    progress(None)
    progress(None)
    capsys.readouterr()
    progress(None)
    assert capsys.readouterr().out == ""


def test_finish_prints_phase_total(capsys):
    progress = PhaseProgress("Phase 1", PLAN, "/nonexistent/progress.log")
    progress.start()
    progress.finish()
    out = capsys.readouterr().out
    assert re.search(r"Phase 1 done in \d+m\d\ds", out)


def test_lines_appended_to_log(tmp_path):
    log_path = tmp_path / "progress.log"
    progress = PhaseProgress("Phase 1", PLAN, log_path)
    progress.start()
    progress(None)
    progress.finish()
    text = log_path.read_text(encoding="utf-8")
    assert "[1/2] define_epic done" in text
    assert "Phase 1 done in" in text


def test_crew_task_callback_wiring():
    pytest.importorskip("crewai")
    from scrum_crew.crew import (
        EXECUTION_TASKS,
        PLANNING_TASKS,
        build_execution_crew,
        build_planning_crew,
        phase_plan,
    )
    assert phase_plan(PLANNING_TASKS)[0] == ("define_epic", "Product Owner")
    assert len(phase_plan(PLANNING_TASKS)) == 7
    assert len(phase_plan(EXECUTION_TASKS)) == 8
    # NOTE: bound-method objects are recreated per attribute access, so
    # `task.callback is calls.append` is always False; hold one object.
    calls = []
    recorder = calls.append
    planning = build_planning_crew(task_callback=recorder)
    assert len(planning.tasks) == 7
    # Propagation to tasks happens in kickoff prep, not construction.
    planning._set_tasks_callbacks()
    assert all(task.callback is recorder for task in planning.tasks)
    execution = build_execution_crew(task_callback=recorder)
    assert len(execution.tasks) == 8
    execution._set_tasks_callbacks()
    assert all(task.callback is recorder for task in execution.tasks)
