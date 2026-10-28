"""Tests for the LLM backend switch (Ollama vs local llama.cpp server).

CrewAI's LLM strips the provider prefix from .model, so the backend
is asserted via .base_url: LiteLLM appends /v1 to the Ollama URL and
keeps an explicit /v1 on the llama-server URL.
"""

import pytest

pytest.importorskip("crewai")

from scrum_crew.crew import build_planning_crew, llm_for_role


def test_default_backend_is_ollama(monkeypatch):
    monkeypatch.delenv("LLAMA_SERVER_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("DEVELOPER_MODEL", raising=False)
    llm = llm_for_role("developer")
    assert llm.model == "qwen3:8b"
    assert llm.base_url == "http://localhost:11434/v1"


def test_llama_server_backend(monkeypatch):
    monkeypatch.setenv("LLAMA_SERVER_URL", "http://localhost:8080/v1")
    llm = llm_for_role("developer")
    assert llm.model == "qwen3:8b"
    assert llm.base_url == "http://localhost:8080/v1"


def test_per_role_model_flows_to_both_backends(monkeypatch):
    monkeypatch.setenv("DEVELOPER_MODEL", "qwen3:4b")
    monkeypatch.delenv("LLAMA_SERVER_URL", raising=False)
    assert llm_for_role("developer").model == "qwen3:4b"
    monkeypatch.setenv("LLAMA_SERVER_URL", "http://localhost:8080/v1")
    assert llm_for_role("developer").model == "qwen3:4b"


def test_crew_agents_use_llama_server_when_set(monkeypatch):
    monkeypatch.setenv("LLAMA_SERVER_URL", "http://localhost:8080/v1")
    crew = build_planning_crew()
    assert len(crew.agents) == 5
    assert all(agent.llm.base_url == "http://localhost:8080/v1"
               for agent in crew.agents)
