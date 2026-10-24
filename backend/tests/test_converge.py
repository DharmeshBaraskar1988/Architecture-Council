import json

from app.agents.runtime import AgentRuntime, register_mock
from app.consensus.engine import Outcome
from app.debate.converge import (compromises, decide_all, evidence_for, merge_votes, needs_revote,
                                 write_statement)
from app.schemas import ArgumentCard, Challenge, Vote

SHORTLIST = [{"id": "x", "status": "candidate"}, {"id": "pci", "status": "binding"},
             {"id": "maybe", "status": "candidate", "depends_on_assumption": True}]


def _card(agent, subject, stance="adopt", **kw):
    return ArgumentCard(agent=agent, subject=subject, stance=stance, claim="c", id=f"{agent}:{subject}", weight=3.0, **kw)


def _check(card, ref, side="for", verdict="verified", weight=3.0, source="prd_fact"):
    return {"card": card, "ref": ref, "side": side, "source": source, "verdict": verdict, "weight": weight}


def _vote(agent, subject, stance="adopt", conf=4, condition=None):
    return Vote(agent=agent, subject=subject, stance=stance, confidence=conf, convinced_by="x", condition=condition)


def test_repeated_fact_counts_once_and_withdrawn_cards_do_not_count():
    cards = [_card("a", "x"), _card("b", "x"), _card("c", "x", conceded=True)]
    checks = [_check("a:x", "F-01"), _check("b:x", "F-01", verdict="partly_supports", weight=1.5),
              _check("c:x", "F-02")]
    ev = evidence_for("x", cards, [], [], checks)
    assert len(ev) == 1 and ev[0].verdict.value == "verified"            # best verdict of the repeated fact


def test_only_challenges_can_be_unanswered_objections():
    cards = [_card("a", "x"), _card("b", "x", "reject")]
    chs = [Challenge(agent="c", target_subject="x", target_agent="a", type="cost", text="t", id="c>a:x",
                     target="a:x", side="against", answered=False)]
    checks = [_check("a:x", "F-01"), _check("b:x", "F-02", side="against"), _check("c>a:x", "F-03", side="against")]
    ev = {e.label.split(" ")[0]: e for e in evidence_for("x", cards, chs, [], checks)}
    assert ev["F-02"].answered is True                                     # a reject card's evidence is not an objection
    assert ev["F-03"].answered is False


def test_decisions_follow_the_rules():
    items = [{"subject": s, "challenges": []} for s in ("x", "pci", "maybe", "empty")]
    votes = [_vote(a, s) for a in ("a", "b", "c") for s in ("x", "pci", "maybe")]
    ds = {d.subject: d for d in decide_all(items, SHORTLIST, votes, [_card("a", "x")], [], [], [_check("a:x", "F-01")])}
    assert ds["pci"].outcome == Outcome.selected and ds["pci"].agreement == 100.0
    assert ds["maybe"].outcome == Outcome.parked
    assert ds["x"].outcome == Outcome.selected and ds["x"].agreement == 100.0
    assert "untested_consensus" in ds["x"].flags[0]                         # nobody challenged x
    assert ds["empty"].outcome == Outcome.reviewer_decides and ds["empty"].agreement is None


def test_split_goes_to_revote_but_capped_does_not():
    items = [{"subject": "x", "challenges": []}]
    votes = [_vote("a", "x", "adopt"), _vote("b", "x", "reject")]
    d = decide_all(items, SHORTLIST, votes, [_card("a", "x")], [], [], [])[0]
    assert d.outcome == Outcome.reviewer_decides and needs_revote(d)        # 50% vote, neutral evidence
    chs = [Challenge(agent="c", target_subject="x", target_agent="a", type="cost", text="t", id="c>a:x",
                     target="a:x", side="against")]
    strong = [_vote(a, "x") for a in "abcd"]
    capped = decide_all(items, SHORTLIST, strong, [_card("a", "x")], chs, [], [_check("c>a:x", "F-09", side="against")])[0]
    assert capped.outcome == Outcome.reviewer_decides and not needs_revote(capped)


def test_revote_replaces_only_revoted_subjects():
    first = [_vote("a", "x", "reject"), _vote("a", "y", "reject"), _vote("b", "x", "adopt")]
    second = [_vote("a", "x", "adopt_with_condition", condition="c")]
    merged = merge_votes(first, second, {"x"})
    assert {(v.agent, v.subject, v.stance.value) for v in merged} == {
        ("a", "x", "adopt_with_condition"), ("a", "y", "reject"), ("b", "x", "adopt")}


def test_compromise_falls_back_to_voters_condition_when_moderator_fails():
    register_mock("moderator", lambda s, u: "no json")
    votes = [_vote("a", "x", "adopt_with_condition", condition="Queue only for video"),
             _vote("b", "x", "adopt_with_condition", condition="Queue only for video"), _vote("c", "x", "reject")]
    items = [{"subject": "x", "challenges": [], "cards": []}]
    ds = {d.subject: d for d in decide_all(items, SHORTLIST, votes, [], [], [], [])}
    assert compromises(AgentRuntime(max_attempts=1), ["x"], items, votes, ds) == {"x": "Queue only for video"}


def test_statement_keeps_guardrails_only_for_conditional_outcomes():
    register_mock("moderator", lambda s, u: json.dumps({"statement": "We build X.",
                                                        "guardrails": {"x": "g", "y": "should be dropped"}}))
    rows = [{"subject": "x", "outcome": "selected_with_condition", "votes": []},
            {"subject": "y", "outcome": "selected", "votes": []},
            {"subject": "z", "outcome": "selected_with_condition", "votes": [{"condition": "from votes"}]}]
    statement, guards, by_model = write_statement(AgentRuntime(), rows)
    assert statement == "We build X." and by_model
    assert guards == {"x": "g", "z": "from votes"}


def test_r7_in_the_graph(tmp_path):
    from test_proposals import S1, _graph
    from app.orchestrator import graph as g

    graph, bus, _ = _graph(tmp_path)
    paused = g.start(graph, "r7", S1, str(tmp_path))
    dec = json.loads((tmp_path / "strategy_decision.json").read_text(encoding="utf-8"))
    assert dec["stage_agreement"] is not None and dec["statement"]
    assert {r["subject"] for r in dec["board"]} == {b["subject"] for b in json.loads(
        (tmp_path / "votes.json").read_text(encoding="utf-8"))["ballot"]}
    assert next(r for r in dec["board"] if r["subject"] == "dpdp_india")["outcome"] == "selected"   # binding
    assert sum(e.type == "consensus.result" for e in bus.events) == len(dec["board"])
    assert bus.events[-1].type == "stage.decided"
    assert paused["for_reviewer"]["pending_rounds"] == [] and paused["for_reviewer"]["outcomes"]
    assert all(r["votes"] for r in dec["board"] if r["agreement"] is not None and r["outcome"] != "selected")


def test_strategy_adr_is_written_and_signed(tmp_path):
    from test_proposals import S1, _graph
    from app.orchestrator import graph as g

    graph, _, _ = _graph(tmp_path)
    g.start(graph, "adr", S1, str(tmp_path))
    doc = (tmp_path / "strategy_adr.md").read_text(encoding="utf-8")
    assert doc.startswith("# Strategy decision: s1_financial_briefing.md")
    for heading in ("## Position statement", "## Decisions", "## Context: facts from the document", "## Reviewer sign-off"):
        assert heading in doc
    assert "India Digital Personal Data Protection Act | Selected" in doc and "_Pending._" in doc
    g.resume(graph, "adr", {"decision": "override", "reason": "Reject ATAM for the pilot"})
    signed = (tmp_path / "strategy_adr.md").read_text(encoding="utf-8")
    assert "**Overridden**" in signed and "Reject ATAM for the pilot" in signed and "_Pending._" not in signed
    assert (tmp_path / "document.json").exists()
