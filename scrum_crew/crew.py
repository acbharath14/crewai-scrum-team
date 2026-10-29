"""CrewAI crew assembly for the Scrum team.

Two sequential crews (see tasks.yaml for the stage list):
  * planning crew:  epic -> stories -> estimates -> convergence -> DoR
  * execution crew: acceptance tests -> implement -> deploy/smoke ->
                    validate -> rework -> review -> retro -> sign-off

The split exists so the human-in-the-loop gates in run.py (PO approval
before execution, final sign-off at the end) can actually interrupt
the flow -- a single kickoff() cannot be paused halfway.

Model strategy (local Ollama only, no paid APIs):
  * Default model for ALL roles: qwen3:8b, the daily-driver local
    model and the strongest choice that runs at usable speed on a
    CPU-only Intel iMac. Override with OLLAMA_MODEL, or per role with
    e.g. DEVELOPER_MODEL / SDET_MODEL.
  * CrewAI talks to Ollama through LiteLLM:
    LLM(model="ollama/<name>", base_url="http://localhost:11434").
  * qwen3-coder:30b is the documented optional Developer upgrade on
    stronger hardware; it is deliberately NOT the default because 30B
    models are too slow on CPU.
  * LLAMA_SERVER_URL switches the backend: when set, agents talk to
    that local server (e.g. llama.cpp on the GPU) as an
    OpenAI-compatible endpoint instead of Ollama. The "openai/"
    prefix only selects the API dialect; requests go to the local
    URL, never to OpenAI. Unset means Ollama on localhost:11434.

Progress reporting: run.py passes a task_callback that prints one
line per finished task (plus a plan upfront and phase totals).
verbose stays False everywhere, so model reasoning traces never
flood the terminal -- the progress lines are the feedback.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from crewai import Agent, Crew, Process, Task, LLM

from .tools import TOOLS_BY_NAME

_HERE = Path(__file__).parent

PLANNING_TASKS = [
    "define_epic",
    "break_down_stories",
    "estimate_developer",
    "estimate_sdet",
    "estimate_analyst",
    "converge_estimates",
    "dor_gate",
]

EXECUTION_TASKS = [
    "write_acceptance_tests",
    "implement",
    "deploy_and_smoke",
    "validate",
    "handle_rework",
    "sprint_review",
    "retrospective",
    "po_signoff",
]


def model_for_role(role_key):
    """Resolve the Ollama model for a role (per-role env wins)."""
    return os.environ.get(f"{role_key.upper()}_MODEL",
                          os.environ.get("OLLAMA_MODEL", "qwen3:8b"))


def llm_timeout_seconds(llama_url):
    """Per-call timeout in seconds, overridable via CREW_LLM_TIMEOUT.

    Converge-style tasks have large prompts and long thinking
    generations, so the default client timeout fires before the
    server finishes, leaving a server request that keeps generating
    while the crew reports a timeout. The llama-server path gets a
    60-minute default, Ollama 30 minutes; both are per call, not
    per run, and both can be overridden with CREW_LLM_TIMEOUT.
    """
    override = os.environ.get("CREW_LLM_TIMEOUT")
    if override:
        return int(override)
    return 3600 if llama_url else 1800


def llm_for_role(role_key):
    """Build the LLM for a role, honoring LLAMA_SERVER_URL.

    When LLAMA_SERVER_URL is set, LiteLLM talks to that local server
    (e.g. llama.cpp on the GPU) as an OpenAI-compatible endpoint; the
    model name is a label -- the server serves whatever it loaded.
    Otherwise the role talks to Ollama on localhost:11434.
    """
    llama_url = os.environ.get("LLAMA_SERVER_URL")
    timeout = llm_timeout_seconds(llama_url)
    if llama_url:
        return LLM(model=f"openai/{model_for_role(role_key)}",
                   base_url=llama_url, api_key="local",
                   timeout=timeout)
    return LLM(model=f"ollama/{model_for_role(role_key)}",
               base_url="http://localhost:11434", timeout=timeout)


def _load_yaml(name):
    with open(_HERE / name, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def build_agents():
    """Build one Agent per role from agents.yaml."""
    configs = _load_yaml("agents.yaml")
    agents = {}
    for key, cfg in configs.items():
        agents[key] = Agent(
            role=cfg["role"],
            goal=cfg["goal"],
            backstory=cfg["backstory"],
            llm=llm_for_role(key),
            tools=[TOOLS_BY_NAME[name] for name in cfg.get("tools", [])],
            allow_delegation=cfg.get("allow_delegation", False),
            verbose=False,
        )
    return agents


def build_tasks(agents, wanted, task_overrides=None):
    """Build Task objects for the named stages, wiring context chains.

    task_overrides maps task name to a full replacement description.
    The runner uses it to inject the initiation requirement and the
    target directory, so agents work on a defined setup instead of
    inventing one. Without overrides, tasks use tasks.yaml verbatim.
    """
    configs = _load_yaml("tasks.yaml")
    tasks = {}
    for name in wanted:
        cfg = configs[name]
        context = [tasks[dep] for dep in cfg.get("context", [])
                   if dep in tasks]
        description = (task_overrides or {}).get(name, cfg["description"])
        tasks[name] = Task(
            description=description,
            expected_output=cfg["expected_output"],
            agent=agents[cfg["agent"]],
            context=context,
        )
    return [tasks[name] for name in wanted]


def phase_plan(wanted):
    """Return [(task_name, agent_role)] for the named stages, in order.

    Used by run.py to print the plan upfront and to label progress
    lines; the order matches build_tasks, and tasks run sequentially,
    so the k-th task_callback call is the k-th plan entry.
    """
    task_configs = _load_yaml("tasks.yaml")
    agent_configs = _load_yaml("agents.yaml")
    plan = []
    for name in wanted:
        agent_key = task_configs[name]["agent"]
        plan.append((name, agent_configs[agent_key]["role"]))
    return plan


def build_planning_crew(task_callback=None, requirement_text=None,
                        target_dir=None):
    """Crew for Phase 1: epic -> stories -> estimates -> DoR.

    When requirement_text is given, it is injected verbatim into the
    define_epic task, so the epic is built ONLY from the defined
    requirement at initiation, never invented by the agent.
    """
    agents = build_agents()
    overrides = {}
    if requirement_text:
        base = _load_yaml("tasks.yaml")["define_epic"]["description"]
        overrides["define_epic"] = (
            "REQUIREMENT (authoritative, provided at initiation; "
            "do not invent scope beyond it):\n"
            f"{requirement_text}\n\n{base} "
            "The epic must cover ONLY this requirement. If any part "
            "of the requirement is ambiguous, record it as an open "
            "question in epic.md, do not invent a feature to fill it."
        )
    return Crew(
        agents=list(agents.values()),
        tasks=build_tasks(agents, PLANNING_TASKS, overrides),
        process=Process.sequential,
        verbose=False,
        task_callback=task_callback,
    )


def build_execution_crew(task_callback=None, target_dir="demo_app"):
    """Crew for Phase 2: tests -> implement -> deploy -> validate -> close.

    target_dir is the defined implementation target. Code goes ONLY
    there, tests go ONLY in tests/, so a run cannot deliver a lone
    file at the repo root like the old CPU run's user.py.
    """
    agents = build_agents()
    configs = _load_yaml("tasks.yaml")
    overrides = {
        "write_acceptance_tests": (
            f"Target app directory is {target_dir}. Write tests ONLY "
            "in tests/, one file per story named "
            "tests/test_<story-id-lowercase>.py, importing from the "
            f"{target_dir} package. "
            f"{configs['write_acceptance_tests']['description']}"
        ),
        "implement": (
            f"Implement ONLY in {target_dir}/. Do not create code "
            "files at the repo root or in any other app directory. "
            f"{configs['implement']['description']}"
        ),
        "deploy_and_smoke": (
            f"Start the app server from {target_dir}/. "
            f"{configs['deploy_and_smoke']['description']}"
        ),
        "validate": (
            "Validate against outputs/sprint.json and the original "
            "requirement in outputs/requirement.md, not against what "
            "was built. "
            f"{configs['validate']['description']}"
        ),
    }
    return Crew(
        agents=list(agents.values()),
        tasks=build_tasks(agents, EXECUTION_TASKS, overrides),
        process=Process.sequential,
        verbose=False,
        task_callback=task_callback,
    )
