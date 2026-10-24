from pathlib import Path
import json

from app.agents.runtime import AgentRuntime, register_mock
from app.events.bus import EventBus
from app.orchestrator import graph as g

FIXTURES = Path(__file__).parent / "fixtures"

S1 = str(FIXTURES / "s1_financial_briefing.md")


def _setup(tmp_path):
    fixture = (FIXTURES / "s1_mock_moderator.json").read_text(encoding="utf-8")
    register_mock("moderator", lambda s, u: fixture)
    bus = EventBus("t1", tmp_path / "debate_log.jsonl")
    return g.build_stage0_graph(AgentRuntime(), bus), bus


def test_graph_pauses_at_reviewer_gate(tmp_path):
    graph, bus = _setup(tmp_path)
    paused = g.start(graph, "t1", S1, str(tmp_path))
    assert paused["paused_at"] == ["reviewer_gate"]
    assert "dpdp_india" in paused["for_reviewer"]["binding"]
    assert paused["for_reviewer"]["pending_rounds"] == []          # every Stage 0 round is built
    assert not (tmp_path / "review.json").exists()          # nothing signed while paused
    assert "reviewer.signed" not in [e.type for e in bus.events]


def test_resume_with_override_records_reason(tmp_path):
    graph, bus = _setup(tmp_path)
    g.start(graph, "t2", S1, str(tmp_path))
    final = g.resume(graph, "t2", {"decision": "override", "reason": "Add GDPR: EU users planned"})
    assert final["review"]["decision"] == "override"
    saved = json.loads((tmp_path / "review.json").read_text(encoding="utf-8"))
    assert saved["reason"] == "Add GDPR: EU users planned"
    assert bus.events[-1].type == "reviewer.signed"


def test_checkpoint_keeps_separate_sessions(tmp_path):
    graph, _ = _setup(tmp_path)
    g.start(graph, "a", S1, str(tmp_path))
    g.start(graph, "b", S1, str(tmp_path))
    assert graph.get_state({"configurable": {"thread_id": "a"}}).next == ("reviewer_gate",)
    g.resume(graph, "a", {"decision": "approve"})
    assert graph.get_state({"configurable": {"thread_id": "a"}}).next == ()
    assert graph.get_state({"configurable": {"thread_id": "b"}}).next == ("reviewer_gate",)


def test_agents_introduce_themselves_at_the_start(tmp_path):
    graph, bus = _setup(tmp_path)
    g.start(graph, "intro", S1, str(tmp_path))
    intros = [e for e in bus.events if e.type == "agent.introduced"]
    assert {e.payload["agent"] for e in intros} == {"moderator", "strategist", "architect", "platform_cost", "critic", "fact_checker"}
    assert all(e.payload["specialty"] and e.payload["works_on"] and e.payload["models"] for e in intros)
    assert bus.events[0].type == "session.started" and bus.events[1].type == "agent.introduced"
