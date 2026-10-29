# CrewAI Scrum Team

A multi-agent Scrum team built with
[CrewAI](https://www.crewai.com/) running on a **local Ollama model** —
no paid APIs, no API keys, no cloud LLM calls. It is built to deliver
on a defined requirement, not to invent one: a real run starts from
a requirement file you write, builds only in the target directory
you name, documents every phase in `outputs/`, and only claims
complete when files, code location, and the test suite all pass.

Five agents play a Scrum team: **Product Owner, Business Analyst,
Scrum Master, Developer, and SDET**. They take a business epic through
stories, joint estimation, readiness and done gates, ATDD acceptance
tests, local deployment, and validation against the **original**
spec — the way a best-performing Scrum team would, including the
uncomfortable parts: estimation disagreements, failed readiness
checks, rework loops with a cap, and scope control.

## The team

| Agent | Owns |
|---|---|
| **Product Owner** | The epic: business goal, scope, explicit out-of-scope. Owns the backlog — only the PO reprioritizes it. Approves sprint execution and signs off the increment. |
| **Business Analyst** | Breaks epics into small INVEST-shaped stories with acceptance criteria, dependencies, and risks. Owns the Definition of Ready gate. |
| **Scrum Master** | The flow: planning, standups, review, retrospective, blockers, WIP limits. Converges estimates and flags divergence. Enforces the rework cap and escalates to the PO. Carries retro actions into the next sprint. |
| **Developer** | Implements stories (code references the story id), keeps tests green, deploys locally, and smoke-checks. Estimates independently before convergence. |
| **SDET** | Writes acceptance tests FROM the acceptance criteria (ATDD), then validates the deployed increment against those same criteria. The validation report is a traceability matrix: every criterion → test(s) → verdict → evidence. No verdict without a cited criterion. |

Why five roles and not the four originally sketched? Without a Scrum
Master, nobody owns the flow — ceremonies, blockers, and WIP limits
belong to no one. See [docs/design.md](docs/design.md) for every
design decision and its reasoning.

## How a sprint flows

```mermaid
flowchart LR
    PO[Product Owner:\ndefine epic] --> AN[Analyst:\nbreak into stories]
    AN --> E1[Developer:\nestimate]
    AN --> E2[SDET:\nestimate]
    AN --> E3[Analyst:\nestimate]
    E1 & E2 & E3 --> SM[Scrum Master:\nconverge estimates]
    SM --> DOR[Analyst:\nDefinition of Ready gate]
    DOR --> GATE{PO approves\nsprint execution?}
    GATE -->|yes| AT[SDET:\nacceptance tests from criteria]
    AT --> DEV[Developer:\nimplement]
    DEV --> DEP[Developer:\ndeploy locally + smoke check]
    DEP --> VAL[SDET:\nvalidate vs ORIGINAL spec]
    VAL -->|FAIL| REW{Rework rounds\n< 2?}
    REW -->|yes| DEV
    REW -->|no| ESC[Escalate to PO:\nscope / split / reject]
    VAL -->|PASS| REV[Scrum Master:\nsprint review]
    REV --> RET[Scrum Master:\nretrospective]
    RET --> SIGN[Product Owner:\nfinal sign-off]
```

Key rules the workflow enforces (all implemented in
`scrum_crew/pipeline.py`, tested without any LLM):

- **Joint estimation, no silent averaging.** Developer, SDET, and
  Analyst estimate each story independently in Fibonacci points. If
  the highest and lowest are more than one Fibonacci step apart, the
  story is flagged DIVERGENT with no locked value — the Scrum Master
  facilitates a discussion first.
- **Definition of Ready gate.** A story enters a sprint only if its
  criteria are clear, dependencies identified, estimate locked at 8
  points or fewer, and it is marked testable.
- **ATDD order.** Acceptance tests are written from the criteria
  before/with implementation, and validation reuses those same
  criteria — the SDET tests what was promised, not what was built.
- **Rework capped at 2 rounds.** A third validation failure escalates
  to the Product Owner instead of looping forever.
- **Scope control.** Requirements discovered mid-sprint go to the
  backlog, never into the running sprint.
- **Definition of Done gate.** Code with story-id references, tests
  passing, criteria validated, local deploy + smoke green, docs
  updated — all five, or it is not Done.

## Layout

```
scrum_crew/
  agents.yaml      one agent per role (CrewAI YAML config)
  tasks.yaml       one task per workflow stage (planning + execution)
  crew.py          crew assembly: sequential process, allow_delegation=False
  tools.py         minimal tools: file read/write, pytest runner
  pipeline.py      pure-stdlib workflow rules (DoR/DoD, convergence,
                   traceability, rework cap) -- no CrewAI import, so
                   tests run without CrewAI installed
  run.py           --demo (scripted) and real crew modes
demo_app/          Team Task Board API (stdlib only): tasks with
                   title/status/assignee/priority, CRUD + validation
examples/sample-run/
                   canned agent outputs for the worked example:
                   epic, stories, estimates, test mapping, ceremony notes
scripts/preflight.py
                   setup checker: installs missing pip deps when
                   testing, checks Ollama, prints fix commands
tests/             pytest suite for pipeline.py + demo_app
docs/design.md     every design decision + modification, with reasoning
```

## Quickstart: scripted demo (no LLM needed)

The scripted demo is the honest way to verify this repo without an
LLM: it replays canned agent text through the **real** pipeline and
runs demo_app's pytest suite **for real**. If the tests fail, the
demo fails.

```bash
python3 -m venv .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m scrum_crew.run --demo
```

Expected demo output: STORY-1..3 (create, list/filter, update) pass
estimation, the Ready gate, validation, and Done. STORY-4 (delete)
is deliberately the disagreement case — Developer 8, SDET 3, Analyst
5, two Fibonacci steps apart — so it is flagged DIVERGENT, fails the
Ready gate, and stays in the backlog for an estimation discussion.
The demo writes `outputs/validation_report.md` (the traceability
matrix) and `outputs/sprint_summary.md`.

## Real crew run: defined setup (on a machine with Ollama)

A real run requires a requirement file. Without one it refuses to
start, so the Product Owner cannot invent a product.

```bash
ollama serve
ollama pull qwen3:8b
.venv/bin/pip install -r requirements.txt
cp examples/defined-setup-requirements.md requirements.md
# edit requirements.md for your product, then:
.venv/bin/python -m scrum_crew.run --requirement requirements.md --target demo_app
.venv/bin/python -m scrum_crew.run --auto --requirement requirements.md --target demo_app
```

What a defined run does, in order, with documentation at each phase:

- Copies your requirement verbatim to `outputs/requirement.md` and
  records its SHA-256, target, backend, and start time in
  `outputs/run_manifest.json`. A previous run's `outputs/` is
  archived to `outputs-<timestamp>/` first, never overwritten.
- Phase 1: epic, stories, estimates, advisory convergence, DoR,
  then a deterministic `outputs/sprint.json` built from stories
  plus estimates, not from LLM arithmetic. Empty sprint stops
  before Phase 2.
- Phase 2: acceptance tests in `tests/` (one file per story),
  implementation only in the target directory, local deploy and
  smoke, validation against the original requirement, rework
  capped at 2, review, retrospective, PO sign-off.
- Gates after Phase 2, in order: all Phase 2 files exist and
  parse, implementation notes and tests_map cite every sprint
  story id, at least one code write went to the target directory
  and at least one test write went to `tests/` (from
  `outputs/tool-calls.log`), then the full pytest suite passes.
  Any gate failure returns 3 and does not print "Sprint complete".
- On success, the runner writes `outputs/delivery.md`
  deterministically from `sprint.json`, the Phase 2 writes, and
  the test result. It does not invent acceptance: accepted items
  are in `outputs/signoff.md`.

Progress: a real run prints the plan upfront (numbered tasks with
agent names), then one line per finished task with elapsed time and
the next task, plus a phase total — the same lines are appended to
`outputs/progress.log`. Model reasoning traces stay off
(`verbose=False`), so the terminal shows where the run is without
flooding it.

Tool confinement: agents can only read and write inside the repo
directory, and test runs are confined to `tests/` — anything outside
is refused with a plain message, not an exception. Every successful
write is logged to `outputs/tool-calls.log`, so you can audit exactly
what the crew changed.

Model strategy: the default model for **all** roles is `qwen3:8b`,
the daily-driver local model and the strongest choice that runs at
usable speed on a CPU-only Intel Mac. Override with `OLLAMA_MODEL`,
or per role with e.g. `DEVELOPER_MODEL`. CrewAI reaches Ollama
through LiteLLM (`ollama/<name>` at `http://localhost:11434`).
`qwen3-coder:30b` is documented as the optional Developer upgrade on
stronger hardware — it is deliberately not the default, because 30B
models are too slow on CPU. Keep tool use minimal per agent: small
local models are fragile with complex tool chains, so agents produce
structured Markdown artifacts instead of long tool loops.

Backend switch: set `LLAMA_SERVER_URL` (e.g.
`http://localhost:8080/v1`) to point the crew at a local llama.cpp
server instead of Ollama — the GPU path for the 2017 iMac via Vulkan.
Unset means Ollama as before.

Preflight (also wired into pytest via `tests/conftest.py`, skippable
with `SCRUM_SKIP_PREFLIGHT=1`) checks the Python version, installs
missing pip packages, and checks Ollama reachability — it prints fix
commands but never installs Ollama or downloads models.

## Honest limitations

- **"Deploy" means local only.** The Developer starts the app server
  on localhost and smoke-checks it. There is no cloud target, no CI
  deploy, and no production environment in this repo.
- **The scripted demo uses canned agent text.** The pipeline checks,
  the traceability matrix, and the tests are real; the agent prose
  is not. The demo proves the workflow machinery, not the model's
  judgment.
- **Small-model tool-use limits.** With qwen3:8b, long tool chains
  are unreliable, which is why each agent gets at most three simple
  tools and tasks demand structured artifacts.
- **The real crew run is unverified until it runs on a machine with
  Ollama.** Sandbox verification covers crew construction (agents and
  tasks load from YAML, the crew object builds) but not a full LLM
  kickoff — there is no Ollama in the sandbox.
- **A defined run is still a local-model run, not a guarantee.**
  An 8B model can still write weak code, miss an edge case, or
  need rework. The gates catch missing files, wrong locations,
  and red suites, but a human must still review `outputs/`,
  `delivery.md`, and the code before treating it as done.
- **In-memory demo storage.** The Task Board loses tasks on restart.
  That is accepted, documented tech debt for the worked example, not
  a recommendation.

## License

MIT — see [LICENSE](LICENSE).
