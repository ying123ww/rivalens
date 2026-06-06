"""Tests for research agent selection fallback behavior."""

import asyncio

from rivalens.research.actions import agent_creator


class DummyConfig:
    smart_llm_model = "test-model"
    smart_llm_provider = "fake"
    llm_kwargs = {}


def test_handle_json_error_with_no_response_returns_default_agent(monkeypatch):
    def fail_json_repair(response):
        raise AssertionError("json_repair should not be called for None responses")

    monkeypatch.setattr(agent_creator.json_repair, "loads", fail_json_repair)

    agent, role = asyncio.run(agent_creator.handle_json_error(None))

    assert agent == "Default Agent"
    assert "critical thinker research assistant" in role


def test_choose_agent_falls_back_when_llm_request_fails(monkeypatch):
    async def fail_completion(**kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(agent_creator, "create_chat_completion", fail_completion)

    agent, role = asyncio.run(agent_creator.choose_agent("test task", DummyConfig()))

    assert agent == "Default Agent"
    assert "critical thinker research assistant" in role
