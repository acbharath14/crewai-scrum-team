"""Pure-stdlib domain logic for the Scrum crew.

This module deliberately imports NOTHING from CrewAI (or any third-party
package) so the workflow rules can be tested without an LLM, without
Ollama, and without CrewAI installed. The CrewAI agents in crew.py
orchestrate; the functions here decide.

Rules implemented (see docs/design.md for reasoning):
  * INVEST-based Definition of Ready (DoR) gate.
  * Joint Fibonacci estimation with a divergence flag.
  * Definition of Done (DoD) gate.
  * Traceability matrix: acceptance criterion -> test(s) -> verdict.
  * Rework loop capped at 2 rounds; the 3rd failure escalates to the PO.
  * Scope control: mid-sprint discoveries go to the backlog, never into
    the running sprint.
"""

from __future__ import annotations

FIBONACCI = [1, 2, 3, 5, 8, 13, 21]
_FIB_INDEX = {value: index for index, value in enumerate(FIBONACCI)}

#: A story larger than this must be split before it can be Ready.
MAX_READY_POINTS = 8

#: Maximum rework rounds before a failing item escalates to the PO.
MAX_REWORK_ROUNDS = 2


# ---------------------------------------------------------------------------
# Estimation
# ---------------------------------------------------------------------------

def converge_estimates(developer, sdet, analyst):
    """Converge three independent Fibonacci estimates into one locked number.

    Returns a dict with the three inputs, their Fibonacci indices, the
    spread in Fibonacci steps, a divergence flag, and the locked value.

    Divergence rule: if the highest and lowest estimates are more than one
    Fibonacci step apart, the team has NOT converged -- the Scrum Master
    must facilitate a discussion before any number is locked. When there
    is no divergence, the locked value is the median of the three.
    """
    estimates = {"developer": developer, "sdet": sdet, "analyst": analyst}
    for role, value in estimates.items():
        if value not in _FIB_INDEX:
            raise ValueError(
                f"{role} estimate {value!r} is not on the Fibonacci scale "
                f"{FIBONACCI}"
            )
    indices = [_FIB_INDEX[value] for value in estimates.values()]
    spread = max(indices) - min(indices)
    divergent = spread > 1
    locked = None if divergent else sorted(estimates.values())[1]
    return {
        "estimates": estimates,
        "spread_steps": spread,
        "divergent": divergent,
        "locked": locked,
    }


# ---------------------------------------------------------------------------
# Artifact schema validation
# ---------------------------------------------------------------------------

def validate_epic(epic):
    """Return a list of problems with an epic dict (empty means valid)."""
    errors = []
    if not isinstance(epic, dict):
        return ["epic must be a mapping"]
    if not epic.get("id"):
        errors.append("epic is missing id")
    if not epic.get("title"):
        errors.append("epic is missing title")
    if not epic.get("business_goal"):
        errors.append("epic is missing business_goal")
    return errors


def validate_story(story):
    """Return a list of problems with a story dict (empty means valid)."""
    errors = []
    if not isinstance(story, dict):
        return ["story must be a mapping"]
    if not story.get("id"):
        errors.append("story is missing id")
    if not story.get("title"):
        errors.append("story is missing title")
    if not story.get("description"):
        errors.append("story is missing description")
    criteria = story.get("acceptance_criteria")
    if not criteria:
        errors.append("story has no acceptance criteria")
    else:
        for criterion in criteria:
            if not isinstance(criterion, dict) or not criterion.get("id"):
                errors.append("acceptance criterion is missing id")
            elif not criterion.get("text"):
                errors.append(f"criterion {criterion['id']} has no text")
    if "dependencies" not in story:
        errors.append("story does not identify dependencies (use [] if none)")
    if "risks" not in story:
        errors.append("story does not identify risks (use [] if none)")
    return errors


# ---------------------------------------------------------------------------
# Definition of Ready (INVEST checklist, owned by the Analyst)
# ---------------------------------------------------------------------------

def dor_check(story, locked_estimate):
    """Check whether a story may enter a sprint.

    locked_estimate is the converged value from converge_estimates, or
    None when estimation diverged. Returns {"passed": bool, "missing": [...]}.
    """
    missing = []
    missing.extend(validate_story(story))
    if locked_estimate is None:
        missing.append("no locked estimate (estimation diverged or missing)")
    elif locked_estimate > MAX_READY_POINTS:
        missing.append(
            f"locked estimate {locked_estimate} exceeds {MAX_READY_POINTS} "
            "points: split the story before it can be Ready"
        )
    if story.get("testable") is not True:
        missing.append("story is not marked testable")
    return {"passed": not missing, "missing": missing}


# ---------------------------------------------------------------------------
# Definition of Done
# ---------------------------------------------------------------------------

def dod_check(story_id, evidence):
    """Check whether a story is Done.

    evidence keys: code_refs (non-empty list of story-ID references),
    tests_passing (bool), criteria_validated (bool: every acceptance
    criterion validated PASS), deployed_smoke (bool: local deploy +
    smoke check green), docs_updated (bool).
    """
    missing = []
    if not evidence.get("code_refs"):
        missing.append("no code references to the story id")
    if evidence.get("tests_passing") is not True:
        missing.append("tests are not all passing")
    if evidence.get("criteria_validated") is not True:
        missing.append("not every acceptance criterion validated PASS")
    if evidence.get("deployed_smoke") is not True:
        missing.append("local deploy + smoke check not green")
    if evidence.get("docs_updated") is not True:
        missing.append("docs not updated")
    return {"story_id": story_id, "passed": not missing, "missing": missing}


# ---------------------------------------------------------------------------
# Traceability matrix (SDET validation against the ORIGINAL spec)
# ---------------------------------------------------------------------------

def build_traceability(criteria, test_results, mapping):
    """Build one matrix row per acceptance criterion.

    criteria: [{"id", "text"}] from the original story spec.
    test_results: {test node id: "PASS"|"FAIL"|"SKIPPED"|"ERROR"}.
    mapping: {criterion id: [test node ids]}.

    Verdict per criterion:
      PASS      -- at least one mapped test, all mapped tests PASS.
      FAIL      -- at least one mapped test FAILed (or ERRORed).
      NOT-RUN   -- mapped tests exist but none ran.
      UNCOVERED -- no test mapped at all (a gap, not a pass).
    No verdict is produced without a cited criterion id.
    """
    rows = []
    for criterion in criteria:
        tests = mapping.get(criterion["id"], [])
        outcomes = [test_results.get(t, "NOT-RUN") for t in tests]
        if not tests:
            verdict = "UNCOVERED"
        elif any(o in ("FAIL", "ERROR") for o in outcomes):
            verdict = "FAIL"
        elif all(o == "PASS" for o in outcomes):
            verdict = "PASS"
        else:
            verdict = "NOT-RUN"
        rows.append({
            "criterion_id": criterion["id"],
            "criterion_text": criterion["text"],
            "tests": tests,
            "outcomes": outcomes,
            "verdict": verdict,
        })
    overall = "PASS" if rows and all(r["verdict"] == "PASS" for r in rows) else "FAIL"
    return {"rows": rows, "overall": overall}


def render_traceability_markdown(matrix):
    """Render a traceability matrix as a Markdown table."""
    lines = [
        "| Acceptance criterion | Test(s) | Outcome | Verdict |",
        "|---|---|---|---|",
    ]
    for row in matrix["rows"]:
        tests = ", ".join(f"`{t}`" for t in row["tests"]) or "_(none)_"
        outcomes = ", ".join(row["outcomes"]) or "_(none)_"
        lines.append(
            f"| {row['criterion_id']}: {row['criterion_text']} "
            f"| {tests} | {outcomes} | **{row['verdict']}** |"
        )
    lines.append(f"\nOverall validation verdict: **{matrix['overall']}**")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rework loop (capped) and scope control
# ---------------------------------------------------------------------------

def next_step_after_failure(failure_count):
    """Decide what happens after a validation failure.

    failure_count is how many times this story has already failed
    validation. Returns ("rework", round_number) while rounds remain,
    else ("escalate", None): the item goes to the Product Owner for a
    scope / split / reject decision instead of looping forever.
    """
    if failure_count < MAX_REWORK_ROUNDS:
        return ("rework", failure_count + 1)
    return ("escalate", None)


def triage_new_requirement(sprint_active):
    """Route a requirement discovered mid-flight.

    A running sprint never absorbs new scope: the item goes to the
    backlog, where only the Product Owner may reprioritize it.
    """
    if sprint_active:
        return "backlog"
    return "sprint_candidate"
