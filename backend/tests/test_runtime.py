import pytest
from pydantic import BaseModel

from app.agents.runtime import AgentError, AgentRuntime, extract_json, register_mock


class Out(BaseModel):
    answer: int


def test_extract_json_with_fence_and_prose():
    assert extract_json('Sure!\n```json\n{"answer": 2}\n```') == {"answer": 2}
    assert extract_json('Here: {"answer": 3} done') == {"answer": 3}


def test_retry_after_invalid_reply():
    replies = iter(['{"answer": "not a number"}', '{"answer": 7}'])
    register_mock("strategist", lambda s, u: next(replies))
    rt = AgentRuntime()
    assert rt.ask("strategist", "sys", "user", Out).answer == 7
    assert [c.ok for c in rt.usage.calls] == [False, True]


def test_gives_up_after_max_attempts():
    register_mock("critic", lambda s, u: "no json here")
    rt = AgentRuntime(max_attempts=2)
    with pytest.raises(AgentError):
        rt.ask("critic", "sys", "user", Out)
    assert len(rt.usage.calls) == 2


class ServiceUnavailableError(Exception):
    pass


def test_transient_provider_error_is_retried_on_same_model():
    replies = iter([ServiceUnavailableError("503 overloaded"), '{"answer": 5}'])

    def reply(s, u):
        r = next(replies)
        if isinstance(r, Exception):
            raise r
        return r
    register_mock("platform_cost", reply)
    rt = AgentRuntime(retry_wait=0)
    assert rt.ask("platform_cost", "sys", "user", Out).answer == 5
    assert [(c.model, c.ok) for c in rt.usage.calls] == [("mock", False), ("mock", True)]


class RateLimitError(Exception):
    pass


def test_rate_limit_waits_as_long_as_the_provider_asks(monkeypatch):
    from app.agents import runtime
    waits = []
    monkeypatch.setattr(runtime.time, "sleep", waits.append)
    replies = iter([RateLimitError("Rate limit reached. Please try again in 12.5s."), '{"answer": 1}'])

    def reply(s, u):
        r = next(replies)
        if isinstance(r, Exception):
            raise r
        return r
    register_mock("critic", reply)
    assert AgentRuntime(retry_wait=1).ask("critic", "sys", "user", Out).answer == 1
    assert waits == [12.5]


def test_used_up_quota_moves_on_without_waiting(monkeypatch):
    from app.agents import runtime
    waits = []
    monkeypatch.setattr(runtime.time, "sleep", waits.append)

    def reply(s, u):
        raise RateLimitError("You exceeded your current quota. limit: 20")
    register_mock("platform_cost", reply)
    rt = AgentRuntime(retry_wait=1)
    with pytest.raises(AgentError):
        rt.ask("platform_cost", "sys", "user", Out)
    assert waits == [] and len(rt.usage.calls) == 1        # straight to the next model (none in mock mode)


def test_fallback_list_is_tried_in_order(monkeypatch):
    from app.agents import runtime
    monkeypatch.setenv("COUNCIL_MOCK_LLM", "0")
    tried = []

    def fake(self, agent, model, msgs, rec):
        tried.append(model)
        if model != "c/third":
            raise RuntimeError("down")
        return '{"answer": 3}'
    monkeypatch.setattr(runtime.AgentRuntime, "_complete", fake)
    rt = AgentRuntime()
    rt.personas = {"x": {"model": "a/first", "fallback_model": ["b/second", "c/third"]}}
    assert rt.ask("x", "s", "u", Out).answer == 3
    assert tried == ["a/first", "b/second", "c/third"]


def test_citation_shapes_models_write_are_accepted():
    from app.schemas import Citation
    assert Citation.model_validate("src-adr-1").model_dump() == {"kind": "source", "ref": "src-adr-1", "quote": None}
    assert Citation.model_validate({"id": "F-02"}).kind.value == "prd_fact"
    assert Citation.model_validate({"kind": "official_docs", "ref": "src-c4_model-1"}).kind.value == "source"
    assert Citation.model_validate({"kind": "precedent", "ref": "dec-1"}).kind.value == "precedent"


def test_unknown_agent():
    with pytest.raises(AgentError):
        AgentRuntime().ask("nobody", "s", "u", Out)


def test_watchers_see_calls_start_and_end():
    seen = []
    register_mock("architect", lambda s, u: '{"answer": 2}')
    rt = AgentRuntime(on_change=lambda r: seen.append((len(r.active), len(r.usage.calls))))
    assert rt.ask("architect", "sys", "user", Out).answer == 2
    assert seen == [(1, 0), (0, 1)]                  # in flight, then finished
    assert rt.usage.calls[0].started


def test_cli_writes_team_and_live_usage(tmp_path):
    import json
    from app.cli import _write_team, _write_usage
    _write_team(tmp_path)
    team = json.loads((tmp_path / "team.json").read_text(encoding="utf-8"))
    assert team["critic"]["name"] == "Rex" and len(team["critic"]["models"]) >= 2
    register_mock("critic", lambda s, u: '{"answer": 4}')
    rt = AgentRuntime(on_change=lambda r: _write_usage(tmp_path, r))
    rt.ask("critic", "sys", "user", Out)
    usage = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    assert usage["active"] == [] and usage["per_call"][0]["agent"] == "critic" and usage["per_call"][0]["ok"]


def test_models_without_a_key_are_skipped(monkeypatch):
    from app.agents.runtime import has_key
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert not has_key("anthropic/claude-sonnet-5-5") and has_key("openai/gpt-4.1") and has_key("mock")
