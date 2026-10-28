# Design decisions

This document records every way the design goes beyond the original
four-role sketch (Product Owner, Analyst, Developer, SDET), plus the
structural choices that make the team actually function. Each entry
states the decision, why, and what breaks without it.

## 1. Added role: Scrum Master

**Decision.** A fifth agent owns ceremonies (sprint planning
facilitation, daily standup, sprint review, retrospective), blocker
tracking, WIP limits, and carrying retrospective action items into
the next sprint.

**Why.** In the four-role sketch, nobody owns flow. The PO owns
scope, the Analyst owns story shape, the Developer owns code, the
SDET owns validation — but standups, blockers, WIP discipline, and
retro follow-through belong to no one, so they silently do not
happen. A best-performing Scrum team has a named flow owner.

**What breaks without it.** Ceremonies become optional, blockers
stay invisible until review day, and retrospective actions die at
the end of the sprint.

## 2. Joint estimation with a divergence flag (not averaging)

**Decision.** Developer, SDET, and Analyst each produce an
independent Fibonacci estimate per story with a written rationale.
The Scrum Master converges them; if the highest and lowest are more
than one Fibonacci step apart, the story is flagged DIVERGENT with
no locked value, and a discussion is required before any number is
locked. When there is no divergence, the locked value is the median.

**Why.** Averaging (or taking the loudest voice) hides disagreement.
A 8 vs 3 split is information: the Developer sees hidden complexity
or the SDET sees trivial testability, and the team needs to find out
which before committing. The worked example demonstrates this on
purpose: STORY-4 (Developer 8, SDET 3, Analyst 5) diverges and stays
in the backlog.

**What breaks without it.** The sprint commits to numbers nobody
believes, and the disagreement surfaces mid-sprint as a missed
commitment.

## 3. Definition of Ready gate (Analyst-owned, INVEST-shaped)

**Decision.** Before a story enters a sprint it must pass: criteria
clear, dependencies identified, estimate locked, locked estimate at
most 8 points (larger stories must split), and marked testable.

**Why.** Sprint churn almost always traces back to half-ready work:
unclear criteria get reinterpreted mid-sprint, unknown dependencies
block the Developer, and oversized stories cannot finish. The gate
is cheap; the churn it prevents is not.

## 4. Definition of Done gate (five evidences, all required)

**Decision.** A story is Done only with all five: code referencing
the story id, tests passing, every acceptance criterion validated,
local deploy + smoke check green, docs updated.

**Why.** "Done" without evidence is how almost-done work piles up.
Each evidence item maps to one way teams cheat Done: untested code,
untested criteria, undeployed code, undocumented behavior.

## 5. ATDD flow + traceability matrix (SDET)

**Decision.** The SDET writes acceptance tests FROM the acceptance
criteria before/with implementation, then validates the deployed
increment against those same criteria. The validation report is a
matrix: every criterion → test(s) → PASS/FAIL verdict → evidence.
A criterion with no test is UNCOVERED, which is a failure, not a
pass. No verdict exists without a cited criterion.

**Why.** Testing against what was built (instead of what was
promised) is how teams pass their own tests and fail the customer.
The matrix makes every verdict auditable back to the original spec,
which is exactly what the SDET role is for.

## 6. Rework loop capped at 2 rounds, then PO escalation

**Decision.** An SDET failure produces a bug story back to the
Developer. After 2 rework rounds, the next failure escalates to the
Product Owner for a scope / split / reject decision instead of
another loop.

**Why.** Uncapped rework is how a sprint burns on one story: each
round feels like progress while the sprint goal dies. The cap forces
the real conversation — is this story wrong, too big, or not worth
it? — while the PO still has options.

## 7. Scope control: mid-sprint discoveries go to the backlog

**Decision.** Requirements discovered during a sprint never enter
the running sprint. They go to the backlog, where only the PO may
reprioritize them.

**Why.** Mid-sprint additions are the top killer of sprint goals.
The rule is boring and absolute on purpose: the sprint commitment
means something only if it cannot be quietly rewritten.

## 8. Human-in-the-loop gates (+ --auto for unattended runs)

**Decision.** Two gates need a human: PO approval before sprint
execution starts, and final sign-off review at the end. `--auto`
skips both for demo/CI runs.

**Why.** An autonomous team that can commit scope and declare
itself done without anyone watching is a liability, not a feature.
The gates are placed where a human decision actually changes the
outcome (commit, accept) — not on every micro-step, which would
make the crew unusable. The crew is split into planning and
execution phases precisely so the first gate can interrupt the flow.

## 9. Risk and dependency tracking (Analyst records, SM surfaces)

**Decision.** The Analyst records dependencies and risks per story
at breakdown time; the Scrum Master surfaces blockers in standup
notes.

**Why.** Dependencies discovered by the Developer mid-sprint are
blockers; dependencies recorded at breakdown time are plan inputs.
Risks work the same way. The split (Analyst records, SM surfaces)
keeps one owner per concern.

## 10. Model strategy: qwen3:8b for all roles, local Ollama only

**Decision.** Default model for every role is qwen3:8b via
LiteLLM (`ollama/<name>`, `http://localhost:11434`), overridable
with `OLLAMA_MODEL` or per-role env vars (e.g.
`DEVELOPER_MODEL`). `qwen3-coder:30b` is documented as the
optional Developer upgrade on stronger hardware and deliberately
not the default.

**Why.** qwen3:8b is the strongest local model that runs at usable
speed on a CPU-only Intel Mac. Defaulting to a 30B model would make
the real crew run unusably slow on the machine it is meant for.
Per-role overrides let a stronger machine specialize (e.g. a coder
model for the Developer) without changing the default path.

## 11. Minimal tool use per agent

**Decision.** Each agent gets at most three simple tools (file
read/write, plus a pytest runner for Developer/SDET). Tasks demand
structured Markdown/JSON artifacts instead of long tool loops.

**Why.** Small local models are fragile with complex tool chains:
each tool call is a chance to derail. Artifact-first tasks keep the
workflow legible and debuggable, and the pipeline rules in
`pipeline.py` (not the model) enforce gates, convergence, and caps.

## 12. Two-phase crew split (planning / execution)

**Decision.** The crew runs as two sequential crews so the PO
approval gate can interrupt between planning and execution.

**Why.** A single `kickoff()` cannot be paused halfway. Without
the split, the human gates would be decorative — the crew would
already have executed before the PO could approve anything.

## 13. Scripted demo: canned text, real machinery

**Decision.** `python -m scrum_crew.run --demo` replays canned
agent outputs through the real pipeline and runs demo_app's pytest
suite for real, exiting non-zero on any failure.

**Why.** A repo whose only verification path needs an LLM cannot be
verified in CI or in a sandbox. The demo proves the workflow
machinery (gates, convergence, traceability, Done) honestly, while
the README states plainly that the agent prose is canned and the
real crew run is unverified until an Ollama machine runs it.

## 14. Worked example: Team Task Board API, stdlib only

**Decision.** The example the crew builds is a one-resource task
API (title/status/assignee/priority, CRUD + validation), stdlib
only, with pytest tests.

**Why.** The example must be small enough to read in one sitting
and runnable without heavy installs, or it stops being a
demonstration and becomes a second project. Stdlib-only keeps the
sandbox verification path dependency-free.

## Deliberately NOT added

- **No separate QA Manager / Release Manager / DevOps roles.**
  Release discipline is covered by the DoD gate + local deploy step,
  and adding roles for a five-agent demo would dilute the core
  story: the four requested roles plus the one missing flow owner.
- **No cloud deployment.** "Deploy" is local start + smoke check.
  A cloud target would need credentials, a provider choice, and
  infrastructure the demo does not need.
- **No multi-epic program management.** One epic, one sprint, one
  worked example. Program-level backlogs are a different demo.
