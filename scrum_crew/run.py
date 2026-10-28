"""Entry point: run the Scrum crew, or replay the scripted demo.

Modes:
  python -m scrum_crew.run --demo
      Scripted demo (no LLM, no Ollama needed). Replays
      examples/sample-run/ through the SAME pipeline the real crew
      uses (estimation convergence, DoR gate, traceability matrix,
      DoD gate) and runs demo_app's pytest suite FOR REAL. Exit
      non-zero when tests fail or any sprint story misses Done.
      Non-interactive by design, so it is safe for CI and sandboxes.

  python -m scrum_crew.run [--auto]
      Real crew run (needs Ollama + qwen3:8b on localhost:11434).
      Phase 1 (planning) runs, then a human-in-the-loop gate asks
      the Product Owner to approve sprint execution, then Phase 2
      (execution) runs, then a final sign-off gate. --auto skips
      both gates for unattended runs.

"Deploy" in this repo means local only: start the app server on
localhost and smoke check it. There is no cloud target.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

from .pipeline import (
    build_traceability,
    converge_estimates,
    dod_check,
    dor_check,
    next_step_after_failure,
    render_traceability_markdown,
    validate_story,
)

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "examples" / "sample-run"
OUTPUTS = ROOT / "outputs"
DEMO_TESTS = "tests/test_demo_app.py"

_RESULT_RE = re.compile(
    r"^(tests/test_demo_app\.py::\S+) (PASSED|FAILED|SKIPPED|ERROR)\b")


def _load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _run_demo_tests():
    """Run demo_app's pytest suite for real; return (exit, {node: outcome})."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", DEMO_TESTS, "-v"],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )
    # pytest -v prints PASSED/FAILED; the pipeline uses PASS/FAIL.
    normalize = {"PASSED": "PASS", "FAILED": "FAIL",
                 "SKIPPED": "SKIPPED", "ERROR": "ERROR"}
    results = {}
    for line in (proc.stdout + proc.stderr).splitlines():
        match = _RESULT_RE.match(line.strip())
        if match:
            results[match.group(1)] = normalize[match.group(2)]
    return proc.returncode, results


def run_demo():
    """Replay the sample run through the real pipeline. Returns exit code."""
    print("== Scrum crew scripted demo ==")
    print("Canned agent text in, real pipeline + real tests out.\n")

    stories_doc = _load_json(SAMPLE / "stories.json")
    tests_map = _load_json(SAMPLE / "tests_map.json")
    tests_map.pop("note", None)
    impl_notes = (SAMPLE / "implementation_notes.md").read_text(encoding="utf-8")

    # -- Phase 1 replay: schema -> convergence -> DoR -------------------
    print("-- Phase 1: planning (epic -> stories -> estimates -> DoR) --")
    sprint, backlog = [], []
    for story in stories_doc["stories"]:
        schema_errors = validate_story(story)
        est = story["estimates"]
        conv = converge_estimates(est["developer"], est["sdet"],
                                  est["analyst"])
        dor = dor_check(story, conv["locked"])
        print(f"{story['id']} {story['title']}: estimates "
              f"dev={est['developer']} sdet={est['sdet']} "
              f"analyst={est['analyst']} spread={conv['spread_steps']} "
              f"divergent={conv['divergent']} locked={conv['locked']} "
              f"DoR={'PASS' if dor['passed'] else 'FAIL'}")
        for reason in dor["missing"]:
            print(f"    DoR gap: {reason}")
        for reason in schema_errors:
            print(f"    schema gap: {reason}")
        target = sprint if (dor["passed"] and not schema_errors) else backlog
        target.append((story, conv))
    print(f"\nSprint scope: {[s['id'] for s, _ in sprint]}")
    print(f"Backlog (not Ready): {[s['id'] for s, _ in backlog]}")
    print("PO approval gate: auto-passed in demo mode.\n")

    # -- Phase 2 replay: real tests -> traceability -> DoD ---------------
    print("-- Phase 2: execution (tests -> traceability -> DoD) --")
    exit_code, test_results = _run_demo_tests()
    n_pass = sum(1 for v in test_results.values() if v == "PASS")
    print(f"pytest {DEMO_TESTS}: exit {exit_code}, "
          f"{n_pass}/{len(test_results)} tests PASS")

    report_lines = ["# Validation report (scripted demo)\n",
                    "SDET validation against the ORIGINAL acceptance "
                    "criteria. Tests above ran for real; verdicts below "
                    "are computed from their actual outcomes.\n"]
    all_done = exit_code == 0
    for story, _conv in sprint:
        matrix = build_traceability(story["acceptance_criteria"],
                                    test_results, tests_map)
        criteria_ok = matrix["overall"] == "PASS"
        story_tests_ok = all(
            test_results.get(t) == "PASS"
            for criterion in story["acceptance_criteria"]
            for t in tests_map.get(criterion["id"], []))
        dod = dod_check(story["id"], {
            "code_refs": [story["id"]] if story["id"] in impl_notes else [],
            "tests_passing": story_tests_ok,
            "criteria_validated": criteria_ok,
            "deployed_smoke": exit_code == 0,
            "docs_updated": story["id"] in impl_notes,
        })
        report_lines.append(f"## {story['id']} {story['title']}\n")
        report_lines.append(render_traceability_markdown(matrix))
        report_lines.append(f"\nDoD: {'PASS' if dod['passed'] else 'FAIL'}")
        if dod["missing"]:
            report_lines.append("  missing: " + "; ".join(dod["missing"]))
        report_lines.append("")
        print(f"{story['id']}: validation {matrix['overall']}, "
              f"DoD {'PASS' if dod['passed'] else 'FAIL'}")
        if not dod["passed"]:
            all_done = False
            step, rnd = next_step_after_failure(0)
            print(f"    -> {step} round {rnd} for {story['id']}; "
                  "cap is 2 rounds, then escalation to the PO")

    OUTPUTS.mkdir(exist_ok=True)
    (OUTPUTS / "validation_report.md").write_text(
        "\n".join(report_lines), encoding="utf-8")
    (OUTPUTS / "sprint_summary.md").write_text(
        "# Sprint summary (scripted demo)\n\n"
        f"Sprint: {', '.join(s['id'] for s, _ in sprint)}\n"
        f"Backlog: {', '.join(s['id'] for s, _ in backlog)}\n"
        f"Tests: {n_pass}/{len(test_results)} PASS, "
        f"pytest exit {exit_code}\n"
        f"All sprint stories Done: {all_done}\n",
        encoding="utf-8")
    print(f"\nWrote {OUTPUTS / 'validation_report.md'}")
    print(f"Wrote {OUTPUTS / 'sprint_summary.md'}")
    print("\nCeremony notes (canned examples):")
    for name in ("standup.md", "review.md", "retrospective.md"):
        print(f"  examples/sample-run/{name}")
    return 0 if all_done else 1


def _ollama_reachable():
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags",
                                    timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def run_real(auto):
    """Run the real CrewAI crew (needs Ollama). Returns exit code."""
    # Imported lazily so --demo never requires CrewAI installed.
    from .crew import build_execution_crew, build_planning_crew

    if not _ollama_reachable():
        print("Ollama is not reachable at http://localhost:11434.")
        print("Fix with:")
        print("  ollama serve")
        print("  ollama pull qwen3:8b")
        return 2
    print("== Phase 1: planning crew ==")
    planning_result = build_planning_crew().kickoff()
    print(planning_result)
    if not auto:
        input("\n[Human gate] Product Owner: press Enter to approve "
              "sprint execution, or Ctrl-C to stop...")
    print("\n== Phase 2: execution crew ==")
    execution_result = build_execution_crew().kickoff()
    print(execution_result)
    if not auto:
        input("\n[Human gate] Product Owner final sign-off: press Enter "
              "to confirm, or Ctrl-C to withhold sign-off...")
    print("Sprint complete.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the Scrum crew or the scripted demo.")
    parser.add_argument("--demo", action="store_true",
                        help="scripted demo: canned agent text + real tests")
    parser.add_argument("--auto", action="store_true",
                        help="skip human-in-the-loop gates (real run only)")
    args = parser.parse_args(argv)
    if args.demo:
        return run_demo()
    return run_real(auto=args.auto)


if __name__ == "__main__":
    raise SystemExit(main())
