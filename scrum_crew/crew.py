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
            llm=LLM(model=f"ollama/{model_for_role(key)}",
                     base_url="http://localhost:11434"),
            tools=[TOOLS_BY_NAME[name] for name in cfg.get("tools", [])],
            allow_delegation=cfg.get("allow_delegation", False),
            verbose=False,
        )
    return agents


def build_tasks(agents, wanted):
    """Build Task objects for the named stages, wiring context chains."""
    configs = _load_yaml("tasks.yaml")
    tasks = {}
    for name in wanted:
        cfg = configs[name]
        context = [tasks[dep] for dep in cfg.get("context", [])
                   if dep in tasks]
        tasks[name] = Task(
            description=cfg["description"],
            expected_output=cfg["expected_output"],
            agent=agents[cfg["agent"]],
            context=context,
        )
    return [tasks[name] for name in wanted]


def build_planning_crew():
    """Crew for Phase 1: epic -> stories -> estimates -> DoR."""
    agents = build_agents()
    return Crew(
        agents=list(agents.values()),
        tasks=build_tasks(agents, PLANNING_TASKS),
        process=Process.sequential,
        verbose=False,
    )


def build_execution_crew():
    """Crew for Phase 2: tests -> implement -> deploy -> validate -> close."""
    agents = build_agents()
    return Crew(
        agents=list(agents.values()),
        tasks=build_tasks(agents, EXECUTION_TASKS),
        process=Process.sequential,
        verbose=False,
    )
