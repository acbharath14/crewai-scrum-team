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
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

from .pipeline import (
    advisory_lock,
    build_traceability,
    converge_estimates,
    dod_check,
    dor_check,
    dor_check_advisory,
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


def _fmt_elapsed(seconds):
    """Format a duration as MmSs (e.g. 65 -> '1m05s')."""
    total = int(seconds)
    return f"{total // 60}m{total % 60:02d}s"


def _append_log(log_path, line):
    """Append one progress line to the log file (best effort)."""
    try:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


class PhaseProgress:
    """Task-level progress for one crew phase (stdlib only, no CrewAI).

    Passed as the crew's task_callback: CrewAI calls it once per
    finished task, and tasks run sequentially in plan order, so the
    k-th call is the k-th plan entry. The callback argument (the
    task output) is intentionally ignored -- the line is built from
    the plan, the agent role, and the measured elapsed time.

    Every printed line is also appended to the progress log, so a
    second terminal (or a later look) shows where the run got to.
    """

    def __init__(self, phase_name, plan, log_path):
        self.phase_name = phase_name
        self.plan = list(plan)
        self.log_path = log_path
        self.index = 0
        self.phase_start = None
        self.last_mark = None

    def _emit(self, line):
        print(line, flush=True)
        _append_log(self.log_path, line)

    def start(self):
        """Print the plan upfront and start the phase clock."""
        self.phase_start = time.monotonic()
        self.last_mark = self.phase_start
        total = len(self.plan)
        for i, (name, role) in enumerate(self.plan, start=1):
            print(f"  {i}. {name} ({role})")
        print(f"  ({total} tasks -- one line per finished task below)")

    def __call__(self, *args):
        """Record one finished task; called by CrewAI per task."""
        if self.index >= len(self.plan):
            return
        name, role = self.plan[self.index]
        now = time.monotonic()
        elapsed = _fmt_elapsed(now - self.last_mark)
        self.last_mark = now
        self.index += 1
        total = len(self.plan)
        if self.index < total:
            nxt = self.plan[self.index][0]
            tail = f"-> next: {nxt}"
        else:
            tail = "-> phase done"
        self._emit(f"[{self.index}/{total}] {name} done -- {role}, "
                   f"{elapsed} {tail}")

    def finish(self):
        """Print the phase total."""
        total = _fmt_elapsed(time.monotonic() - self.phase_start)
        self._emit(f"{self.phase_name} done in {total}")


def _ollama_reachable():
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags",
                                    timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _url_reachable(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _backend_reachable():
    """Check the backend the crew will actually use, not just Ollama.

    The old check always probed Ollama, so a llama-server run could
    abort because Ollama was off even though its server was healthy,
    or pass because Ollama was on while its server was off.
    """
    llama_url = os.environ.get("LLAMA_SERVER_URL")
    if llama_url:
        base = llama_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3].rstrip("/")
        return _url_reachable(f"{base}/health")
    return _ollama_reachable()


def _estimate_value(entry):
    """Extract a Fibonacci point from an estimate file entry.

    Estimate files map story id to {points, rationale} (the task
    format), or to a bare int. Anything else is invalid, not a
    guessable number.
    """
    if isinstance(entry, int) and not isinstance(entry, bool):
        return entry
    if isinstance(entry, dict):
        points = entry.get("points")
        if isinstance(points, int) and not isinstance(points, bool):
            return points
    return None


def _validate_outputs(outputs_dir, expected):
    """Validate expected output files: exist, non-empty, JSON parses.

    expected maps task name to (filename, owner role). Returns a
    list of error strings naming the owner and file, empty on pass.
    A task counts as done only when its file exists; terminal text
    alone is not done.
    """
    errors = []
    for task_name, (filename, owner) in expected.items():
        path = Path(outputs_dir) / filename
        if not path.exists():
            errors.append(f"{task_name} ({owner}): missing {filename}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{task_name} ({owner}): unreadable {filename}: {exc}")
            continue
        if not text.strip():
            errors.append(f"{task_name} ({owner}): empty {filename}")
            continue
        if filename.endswith(".json"):
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                errors.append(f"{task_name} ({owner}): invalid JSON in {filename}: {exc}")
    return errors


def _build_sprint_json(outputs_dir):
    """Build outputs/sprint.json deterministically from Phase 1 files.

    This is the contract Phase 2 and PO sign-off read. It is computed
    with pipeline.advisory_lock() and dor_check_advisory(), not taken
    from the LLM's estimates_locked.json, so an LLM spread-math error
    cannot block a story: [5, 8, 8] locks at 8, not null. Returns
    (sprint, backlog, errors). Sprint is empty only when no story
    passes DoR, in which case the caller must stop before Phase 2.
    """
    outputs_dir = Path(outputs_dir)
    errors = []

    def load_json(name):
        path = outputs_dir / name
        if not path.exists():
            errors.append(f"missing {name}")
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid {name}: {exc}")
            return None

    stories_doc = load_json("stories.json")
    if stories_doc is None:
        return [], [], errors
    if isinstance(stories_doc, dict):
        stories = stories_doc.get("stories")
    else:
        stories = stories_doc
    if not isinstance(stories, list):
        errors.append("stories.json has no stories list")
        return [], [], errors
    estimate_docs = {}
    for role, name in (("developer", "estimates_developer.json"),
                       ("sdet", "estimates_sdet.json"),
                       ("analyst", "estimates_analyst.json")):
        estimate_docs[role] = load_json(name)
    if errors:
        return [], [], errors

    sprint, backlog = [], []
    for story in stories:
        story_id = story.get("id") if isinstance(story, dict) else None
        if not story_id:
            errors.append("story without id in stories.json")
            continue
        values = {}
        for role, doc in estimate_docs.items():
            if not isinstance(doc, dict) or story_id not in doc:
                errors.append(f"missing estimate for {story_id} in {role} file")
                values = None
                break
            points = _estimate_value(doc[story_id])
            if points is None:
                errors.append(f"invalid estimate for {story_id} in {role} file")
                values = None
                break
            values[role] = points
        if values is None:
            continue
        try:
            lock = advisory_lock(values["developer"], values["sdet"],
                                 values["analyst"])
        except ValueError as exc:
            errors.append(f"invalid estimate for {story_id}: {exc}")
            continue
        dor = dor_check_advisory(story, lock["locked"])
        entry = {
            "id": story_id,
            "title": story.get("title"),
            "locked": lock["locked"],
            "estimates": lock["estimates"],
            "spread_steps": lock["spread_steps"],
            "divergent_advisory": lock["divergent"],
            "snapped_from": lock.get("snapped_from", {}),
        }
        if dor["passed"]:
            entry["warnings"] = dor["warnings"]
            sprint.append(entry)
        else:
            entry["reasons"] = dor["missing"]
            entry["warnings"] = dor["warnings"]
            backlog.append(entry)
    if errors:
        return [], [], errors
    sprint_doc = {"sprint": sprint, "backlog": backlog,
                  "generated_from": ["stories.json",
                                     "estimates_developer.json",
                                     "estimates_sdet.json",
                                     "estimates_analyst.json"]}
    (outputs_dir / "sprint.json").write_text(
        json.dumps(sprint_doc, indent=2), encoding="utf-8")
    return sprint, backlog, errors


def _load_requirement(path):
    """Load a requirement file; empty or missing is a hard error.

    A defined-setup run never invents an epic. If no requirement
    is supplied, the runner refuses to start, instead of letting
    the Product Owner invent a product.
    """
    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"requirement file {path} is empty")
    return text


def _resolve_target(target, root=ROOT):
    """Resolve a target dir inside the repo; raise on escape/missing."""
    base = Path(root).resolve()
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        raise ValueError(f"target {target} is outside the repo directory")
    if not resolved.is_dir():
        raise ValueError(f"target {target} is not an existing directory")
    return resolved


def _archive_previous_outputs(outputs_dir=OUTPUTS, root=ROOT):
    """Archive a previous run's outputs/ instead of overwriting it.

    Returns the archive path, or None when outputs/ is empty or
    absent. Code in the target directory is NOT archived: a new
    sprint builds on the previous increment, it does not wipe it.
    """
    outputs_dir = Path(outputs_dir)
    if not outputs_dir.exists():
        return None
    if not any(outputs_dir.iterdir()):
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive = Path(root) / f"outputs-{stamp}"
    outputs_dir.rename(archive)
    return archive


def _write_run_manifest(outputs_dir, requirement_path, requirement_text,
                        target_dir, auto):
    """Write outputs/run_manifest.json: the audit record for the run."""
    manifest = {
        "requirement_file": str(requirement_path),
        "requirement_sha256": hashlib.sha256(
            requirement_text.encode("utf-8")).hexdigest(),
        "target": str(target_dir),
        "auto": auto,
        "backend": "llama-server" if os.environ.get("LLAMA_SERVER_URL")
        else "ollama",
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (Path(outputs_dir) / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _phase2_writes(log_path, offset, root=ROOT):
    """Parse tool-calls.log writes made after a byte offset."""
    log_path = Path(log_path)
    if not log_path.exists():
        return []
    text = log_path.read_bytes()[offset:].decode("utf-8", errors="replace")
    writes = []
    for line in text.splitlines():
        if " write " not in line:
            continue
        middle = line.split(" write ", 1)[1]
        path_text = middle.rsplit(" (", 1)[0]
        try:
            rel = Path(path_text).resolve().relative_to(Path(root).resolve())
        except ValueError:
            continue
        writes.append(str(rel))
    return writes


def _validate_delivery(sprint, outputs_dir, target_dir, log_offset,
                       root=ROOT):
    """Validate Phase 2 delivery, not just Phase 2 files.

    Errors when: implementation notes or tests_map do not mention a
    sprint story id, no code write went to the target directory,
    or no test write went to tests/ since Phase 2 started. This
    is what catches a run that talks about code in terminal text
    but writes nothing, or writes a lone file at the repo root.
    """
    outputs_dir = Path(outputs_dir)
    errors = []
    notes = (outputs_dir / "implementation_notes.md").read_text(
        encoding="utf-8") if (outputs_dir / "implementation_notes.md").exists() else ""
    tests_map = (outputs_dir / "tests_map.json").read_text(
        encoding="utf-8") if (outputs_dir / "tests_map.json").exists() else ""
    for story in sprint:
        story_id = story["id"]
        if story_id not in notes:
            errors.append(f"implementation_notes.md does not mention {story_id}")
        if story_id not in tests_map:
            errors.append(f"tests_map.json does not mention {story_id}")
    writes = _phase2_writes(outputs_dir / "tool-calls.log", log_offset, root)
    target_prefix = str(target_dir).rstrip("/") + "/"
    if not any(w.startswith(target_prefix) for w in writes):
        errors.append(f"no code write to {target_dir}/ in Phase 2")
    if not any(w.startswith("tests/") for w in writes):
        errors.append("no test write to tests/ in Phase 2")
    return errors, writes


def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _story_criteria(outputs_dir, sprint_ids):
    """Map sprint story id to its acceptance criterion ids."""
    stories_doc = {}
    try:
        stories_doc = json.loads(
            (Path(outputs_dir) / "stories.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(stories_doc, dict):
        stories = stories_doc.get("stories", [])
    else:
        stories = stories_doc
    result = {}
    for story in stories:
        if not isinstance(story, dict) or story.get("id") not in sprint_ids:
            continue
        criteria = story.get("acceptance_criteria", [])
        result[story["id"]] = [
            c.get("id") for c in criteria if isinstance(c, dict) and c.get("id")]
    return result


def _validate_closure(sprint, backlog, outputs_dir, target_dir, writes,
                      root=ROOT):
    """Deterministic sprint closure audit.

    Returns (errors, checklist). Checklist is a list of
    (name, ok, detail). Every deliverable is checked, not just
    counted as existing: criterion coverage, code per story,
    test file per story, notes listing code files, review
    naming deliverables, sign-off naming sprint and backlog.
    A thin summary that omits a deliverable fails, even if the
    file exists.
    """
    outputs_dir = Path(outputs_dir)
    sprint_ids = [s["id"] for s in sprint]
    backlog_ids = [s["id"] for s in backlog]
    criteria = _story_criteria(outputs_dir, sprint_ids)
    all_criteria = [c for ids in criteria.values() for c in ids]
    texts = {name: _read_text(outputs_dir / name) for name in [
        "requirement.md", "epic.md", "implementation_notes.md",
        "tests_map.json", "deploy_smoke.md", "validation_report.md",
        "rework_log.md", "review.md", "retrospective.md", "signoff.md"]}
    code_writes = [w for w in writes
                   if w.startswith(str(target_dir).rstrip("/") + "/")]
    test_writes = [w for w in writes if w.startswith("tests/")]
    checklist = []

    def check(name, ok, detail):
        checklist.append((name, ok, detail))
        return ok

    check("requirement.md present", bool(texts["requirement.md"].strip()),
          "requirement.md is missing or empty")
    check("epic.md present", bool(texts["epic.md"].strip()),
          "epic.md is missing or empty")
    check("sprint.json present",
          (outputs_dir / "sprint.json").exists(),
          "sprint.json is missing")
    for story_id in sprint_ids:
        check(f"tests_map cites {story_id}",
              story_id in texts["tests_map.json"],
              f"tests_map.json does not mention {story_id}")
        check(f"implementation_notes cites {story_id}",
              story_id in texts["implementation_notes.md"],
              f"implementation_notes.md does not mention {story_id}")
        check(f"deploy_smoke cites {story_id}",
              story_id in texts["deploy_smoke.md"],
              f"deploy_smoke.md does not mention {story_id}")
        check(f"review cites {story_id}",
              story_id in texts["review.md"],
              f"review.md does not mention {story_id}")
        check(f"signoff cites {story_id}",
              story_id in texts["signoff.md"],
              f"signoff.md does not mention {story_id}")
        expected_test = f"tests/test_{story_id.lower()}.py"
        test_path = Path(root) / expected_test
        test_text = _read_text(test_path) if test_path.exists() else ""
        check(f"test file {expected_test}",
              test_path.exists() and "def test_" in test_text
              and (story_id in test_text
                   or any(c in test_text for c in criteria.get(story_id, []))),
              f"{expected_test} is missing, has no test, or cites neither "
              f"{story_id} nor its criteria")
        code_texts = [_read_text(Path(root) / w) for w in code_writes]
        check(f"code cites {story_id}",
              any(story_id in t for t in code_texts),
              f"no Phase 2 code file cites {story_id}")
    for criterion in all_criteria:
        check(f"tests_map covers {criterion}",
              criterion in texts["tests_map.json"],
              f"tests_map.json does not cover {criterion}")
        check(f"validation covers {criterion}",
              criterion in texts["validation_report.md"],
              f"validation_report.md does not cover {criterion}")
    check("validation has verdicts",
          "PASS" in texts["validation_report.md"]
          or "FAIL" in texts["validation_report.md"],
          "validation_report.md has no PASS/FAIL verdict")
    for code_file in code_writes:
        check(f"notes list {code_file}",
              code_file in texts["implementation_notes.md"],
              f"implementation_notes.md does not list {code_file}")
    for test_file in test_writes:
        check(f"tests_map lists {test_file}",
              test_file in texts["tests_map.json"],
              f"tests_map.json does not list {test_file}")
    check("deploy_smoke mentions server",
          "server" in texts["deploy_smoke.md"].lower(),
          "deploy_smoke.md does not mention a server")
    if "FAIL" in texts["validation_report.md"]:
        check("rework addresses failures",
              "rework" in texts["rework_log.md"].lower()
              or "escalat" in texts["rework_log.md"].lower(),
              "validation has FAIL but rework_log.md does not mention "
              "rework or escalation")
    check("retrospective has owned actions",
          "owner" in texts["retrospective.md"].lower(),
          "retrospective.md names no owner for its actions")
    if backlog_ids:
        check("signoff names backlog",
              "backlog" in texts["signoff.md"].lower(),
              "signoff.md does not name the backlog")
        for backlog_id in backlog_ids:
            check(f"signoff names backlog {backlog_id}",
                  backlog_id in texts["signoff.md"],
                  f"signoff.md does not name backlog {backlog_id}")
    check("run_manifest present",
          (outputs_dir / "run_manifest.json").exists(),
          "run_manifest.json is missing")
    errors = [detail for _name, ok, detail in checklist if not ok]
    return errors, checklist


def _write_closure_audit(outputs_dir, checklist):
    lines = ["# Sprint closure audit", ""]
    for name, ok, detail in checklist:
        lines.append(f"- [{'PASS' if ok else 'FAIL'}] {name}"
                     + ("" if ok else f": {detail}"))
    (Path(outputs_dir) / "closure_audit.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def _write_backlog_doc(outputs_dir, backlog):
    lines = ["# Backlog for next sprint", "",
             "These stories did not enter the sprint. The Product Owner "
             "reprioritizes them for a future sprint; they are NOT "
             "automatically included in the next run.", ""]
    if not backlog:
        lines.append("No backlog stories.")
    for story in backlog:
        reasons = "; ".join(story.get("reasons", []))
        lines.append(f"- {story['id']}: {story.get('title', '')}"
                     + (f" - {reasons}" if reasons else ""))
    (Path(outputs_dir) / "backlog.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def _write_delivery_doc(outputs_dir, sprint, backlog, writes, test_ok,
                        checklist=None):
    """Write outputs/delivery.md deterministically from run evidence."""
    lines = ["# Delivery", "",
             "Sprint stories (from outputs/sprint.json):"]
    for story in sprint:
        lines.append(f"- {story['id']}: {story.get('title', '')} "
                     f"(advisory locked {story.get('locked')})")
    lines.append("")
    lines.append("Backlog (not Ready):")
    for story in backlog:
        lines.append(f"- {story['id']}: {story.get('title', '')}")
    lines.append("")
    lines.append("Files written in Phase 2 (from outputs/tool-calls.log):")
    for path in sorted(set(writes)):
        lines.append(f"- {path}")
    lines.append("")
    lines.append(f"Test suite gate: {'PASS' if test_ok else 'FAIL'}")
    if checklist:
        lines.append("")
        lines.append("Closure audit (from outputs/closure_audit.md):")
        for name, ok, _detail in checklist:
            lines.append(f"- [{'PASS' if ok else 'FAIL'}] {name}")
    lines.append("")
    lines.append("Backlog for next sprint: outputs/backlog.md")
    lines.append("PO sign-off file: outputs/signoff.md "
                 "(see that file for accepted items; this delivery "
                 "doc does not invent acceptance).")
    (Path(outputs_dir) / "delivery.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def _run_test_suite(path="tests", python=sys.executable, timeout=300):
    """Run the full pytest suite deterministically, return (ok, tail).

    This is the gate the CPU run lacked: a test file like the old
    tests/test_c1.py, which failed with NameError because it never
    imported User, must block sign-off, not be ignored while the
    crew prints terminal text. Timeout is 300s, matching tools.
    """
    try:
        proc = subprocess.run(
            [python, "-m", "pytest", path, "-q"],
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "test run timed out after 300s"
    tail = (proc.stdout + proc.stderr)[-3000:]
    return proc.returncode == 0, tail


PHASE1_EXPECTED = {
    "define_epic": ("epic.md", "Product Owner"),
    "break_down_stories": ("stories.json", "Business Analyst"),
    "estimate_developer": ("estimates_developer.json", "Developer"),
    "estimate_sdet": ("estimates_sdet.json", "SDET"),
    "estimate_analyst": ("estimates_analyst.json", "Business Analyst"),
    "converge_estimates": ("estimates_locked.json", "Scrum Master"),
    "dor_gate": ("dor_report.md", "Business Analyst"),
}

PHASE2_EXPECTED = {
    "write_acceptance_tests": ("tests_map.json", "SDET"),
    "implement": ("implementation_notes.md", "Developer"),
    "deploy_and_smoke": ("deploy_smoke.md", "Developer"),
    "validate": ("validation_report.md", "SDET"),
    "handle_rework": ("rework_log.md", "Scrum Master"),
    "sprint_review": ("review.md", "Scrum Master"),
    "retrospective": ("retrospective.md", "Scrum Master"),
    "po_signoff": ("signoff.md", "Product Owner"),
}


def _check_resume(outputs_dir, requirement_text, target_rel):
    """Check a resume is safe: same requirement, same target.

    Returns a list of errors, empty when resume is allowed. A
    changed requirement means Phase 1 is stale, so resume is
    refused instead of running Phase 2 on old stories.
    """
    manifest_path = Path(outputs_dir) / "run_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["run_manifest.json is missing, cannot resume; "
                "run a full run instead"]
    errors = []
    expected_sha = hashlib.sha256(
        requirement_text.encode("utf-8")).hexdigest()
    if manifest.get("requirement_sha256") and \
            manifest["requirement_sha256"] != expected_sha:
        errors.append("requirement file changed since Phase 1; "
                      "resume refused, re-run Phase 1 with the new "
                      "requirement")
    if manifest.get("target") and manifest["target"] != target_rel:
        errors.append(f"target changed since Phase 1 "
                      f"({manifest['target']} vs {target_rel}); "
                      "resume refused")
    return errors


def run_real(auto, requirement_path=None, target_dir="demo_app",
             resume=False):
    """Run the real CrewAI crew on a defined requirement.

    Defined-setup mode: requirement_path is mandatory. Without it
    the run refuses to start, because an invented epic is not a
    defined setup. target_dir is the only directory code may go to.
    With resume=True, Phase 1 is skipped: existing Phase 1 files
    in outputs/ are validated, the runner's sprint.json is built,
    and Phase 2 runs only. outputs/ is NOT archived on resume.
    Returns exit code.
    """
    # Imported lazily so --demo never requires CrewAI installed.
    from .crew import (
        EXECUTION_TASKS,
        PLANNING_TASKS,
        build_execution_crew,
        build_planning_crew,
        phase_plan,
    )

    if requirement_path is None:
        print("Real run requires --requirement FILE.")
        print("Create a requirements file first, then run with:")
        print("  python -m scrum_crew.run --auto "
              "--requirement requirements.md --target demo_app")
        print("An invented epic is not a defined setup.")
        return 2
    try:
        requirement_text = _load_requirement(requirement_path)
        target_resolved = _resolve_target(target_dir)
        target_rel = str(target_resolved.relative_to(ROOT.resolve()))
    except (OSError, ValueError) as exc:
        print(f"Defined-setup error: {exc}")
        return 2
    if not _backend_reachable():
        llama_url = os.environ.get("LLAMA_SERVER_URL")
        if llama_url:
            print(f"Llama server is not reachable at {llama_url}.")
            print("Fix with:")
            print("  scripts/llama-vulkan.sh start")
        else:
            print("Ollama is not reachable at http://localhost:11434.")
            print("Fix with:")
            print("  ollama serve")
            print("  ollama pull qwen3:8b")
        return 2
    if resume:
        if not OUTPUTS.exists():
            print("Cannot resume: outputs/ does not exist. "
                  "Run a full run instead.")
            return 2
        errors = _check_resume(OUTPUTS, requirement_text, target_rel)
        if errors:
            for error in errors:
                print(f"Resume refused: {error}")
            return 2
        print("Resuming from existing Phase 1 outputs in outputs/.")
        print("Phase 1 crew skipped; outputs/ will NOT be archived.")
        print(f"Target: {target_rel}")
        log_path = OUTPUTS / "progress.log"
        _append_log(log_path,
                    f"== resume {time.strftime('%Y-%m-%d %H:%M:%S')} ==")
    else:
        archived = _archive_previous_outputs()
        if archived:
            print(f"Previous outputs archived to {archived}")
        OUTPUTS.mkdir(exist_ok=True)
        (OUTPUTS / "requirement.md").write_text(requirement_text,
                                                 encoding="utf-8")
        manifest = _write_run_manifest(OUTPUTS, requirement_path,
                                       requirement_text, target_rel, auto)
        print(f"Requirement: {manifest['requirement_file']} "
              f"(sha256 {manifest['requirement_sha256'][:12]}...)")
        print(f"Target: {target_rel}")
        log_path = OUTPUTS / "progress.log"
        _append_log(log_path,
                    f"== run {time.strftime('%Y-%m-%d %H:%M:%S')} ==")
        print("== Phase 1: planning crew ==")
        planning_progress = PhaseProgress(
            "Phase 1", phase_plan(PLANNING_TASKS), log_path)
        planning_progress.start()
        planning_result = build_planning_crew(
            task_callback=planning_progress,
            requirement_text=requirement_text).kickoff()
        planning_progress.finish()
        print(planning_result)
    # -- Phase 1 gate: files, not terminal text, are done ------------
    errors = _validate_outputs(OUTPUTS, PHASE1_EXPECTED)
    if errors:
        print("\nPhase 1 incomplete, stopping before Phase 2:")
        for error in errors:
            print(f"  - {error}")
        print("Fix the named owner/file and re-run; do not proceed "
              "to execution with a missing planning output.")
        return 3
    sprint, backlog, errors = _build_sprint_json(OUTPUTS)
    if errors:
        print("\nPhase 1 sprint contract failed, stopping before Phase 2:")
        for error in errors:
            print(f"  - {error}")
        return 3
    print(f"\nSprint scope (from outputs/sprint.json): "
          f"{[s['id'] for s in sprint]}")
    print(f"Backlog (not Ready): {[s['id'] for s in backlog]}")
    if not sprint:
        print("\nSprint scope is empty, stopping before Phase 2.")
        print("Backlog reasons:")
        for entry in backlog:
            print(f"  - {entry['id']}: {'; '.join(entry.get('reasons', []))}")
        print("No execution crew runs on an empty sprint.")
        return 3
    if not auto:
        input("\n[Human gate] Product Owner: press Enter to approve "
              "sprint execution, or Ctrl-C to stop...")
    print("\n== Phase 2: execution crew ==")
    tool_log = OUTPUTS / "tool-calls.log"
    log_offset = tool_log.stat().st_size if tool_log.exists() else 0
    execution_progress = PhaseProgress(
        "Phase 2", phase_plan(EXECUTION_TASKS), log_path)
    execution_progress.start()
    execution_result = build_execution_crew(
        task_callback=execution_progress,
        target_dir=target_rel).kickoff()
    execution_progress.finish()
    print(execution_result)
    if not auto:
        input("\n[Human gate] Product Owner final sign-off: press Enter "
              "to confirm, or Ctrl-C to withhold sign-off...")
    errors = _validate_outputs(OUTPUTS, PHASE2_EXPECTED)
    if errors:
        print("\nPhase 2 incomplete, sprint is NOT complete:")
        for error in errors:
            print(f"  - {error}")
        print("A task counts as done only when its file exists; "
              "terminal text alone is not done.")
        return 3
    errors, writes = _validate_delivery(sprint, OUTPUTS, target_rel,
                                        log_offset)
    if errors:
        print("\nPhase 2 delivery incomplete, sprint is NOT complete:")
        for error in errors:
            print(f"  - {error}")
        print("Code must be written to the target directory and "
              "tests to tests/, and both docs must cite every "
              "sprint story id.")
        return 3
    _write_backlog_doc(OUTPUTS, backlog)
    errors, checklist = _validate_closure(sprint, backlog, OUTPUTS,
                                          target_rel, writes)
    _write_closure_audit(OUTPUTS, checklist)
    if errors:
        print("\nSprint closure audit FAILED, sprint is NOT complete:")
        for error in errors:
            print(f"  - {error}")
        print("Full checklist in outputs/closure_audit.md. Fix the "
              "named gaps and re-run; a thin summary does not close "
              "a sprint.")
        return 3
    print("\n== Test suite gate: full pytest run ==")
    ok, tail = _run_test_suite()
    if not ok:
        print("Test suite FAILED, sprint is NOT complete:")
        print(tail)
        print("Fix the failing tests and re-run; a red suite blocks "
              "sign-off, even when all output files exist.")
        return 3
    manifest_path = OUTPUTS / "run_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
    manifest.update({"sprint": [s["id"] for s in sprint],
                     "backlog": [s["id"] for s in backlog],
                     "test_gate": "PASS" if ok else "FAIL",
                     "closure_audit": "PASS",
                     "ended_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    manifest_path.write_text(json.dumps(manifest, indent=2),
                             encoding="utf-8")
    _write_delivery_doc(OUTPUTS, sprint, backlog, writes, ok, checklist)
    print("Delivery documented in outputs/delivery.md")
    print("Sprint complete.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the Scrum crew or the scripted demo.")
    parser.add_argument("--demo", action="store_true",
                        help="scripted demo: canned agent text + real tests")
    parser.add_argument("--auto", action="store_true",
                        help="skip human-in-the-loop gates (real run only)")
    parser.add_argument("--requirement", default=None,
                        help="requirement file for a real run (mandatory)")
    parser.add_argument("--target", default="demo_app",
                        help="target app directory inside the repo")
    parser.add_argument("--resume", action="store_true",
                        help="skip Phase 1, run Phase 2 from existing "
                        "outputs/ (requirement and target must match "
                        "the original run)")
    args = parser.parse_args(argv)
    if args.demo:
        return run_demo()
    return run_real(auto=args.auto, requirement_path=args.requirement,
                    target_dir=args.target, resume=args.resume)


if __name__ == "__main__":
    raise SystemExit(main())
