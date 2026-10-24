import json
from datetime import datetime, timedelta, timezone

from app.agents.runtime import AgentRuntime, register_mock
from app.factcheck.verdicts import fact_check, summary
from app.knowledge.crawler import Page, page_id, save_page
from app.schemas import ArgumentCard, Citation, Fact, FactSheet, FactStatus, Verdict

SHEET = FactSheet(document="t", facts=[
    Fact(id="F-01", key="team_size", value=6, quote="The team has six developers.", page=2, status=FactStatus.confirmed),
    Fact(id="F-02", key="cloud_provider", value="azure", quote="We run on Azure.", page=2, status=FactStatus.confirmed),
    Fact(id="F-03", key="card_payments", value=False, status=FactStatus.assumed),
])
URL = "https://12factor.net/config"
SOURCES = {"src-x-1": {"framework": "x", "kind": "official_docs", "verified": False, "url": "https://12factor.net/"},
           "src-x-2": {"framework": "x", "kind": "official_docs", "verified": True, "url": URL, "title": "Config"},
           "src-x-3": {"framework": "x", "kind": "official_docs", "verified": False, "stale": True, "url": URL}}


def _store(url=URL, days_old=0):
    when = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat(timespec="seconds")
    save_page(Page(id=page_id(url), url=url, domain="12factor.net", ok=True, title="Config",
                   text="Intro about apps.\n" * 80 + "Store config in the environment, never in code.\n" + "Other text.\n" * 80,
                   fetched_at=when))


def _card(cid, stance="adopt", facts=(), cites=()):
    agent, subject = cid.split(":")
    return ArgumentCard(agent=agent, subject=subject, stance=stance, claim=f"claim {cid}", facts=list(facts),
                        citations=[Citation(kind="source", ref=r) for r in cites], id=cid)


def _judge(answers: dict[str, str]):
    """Mock judge: answers by the fact key named in each item's evidence."""
    asked = []

    def reply(s, u):
        items = json.loads(u)
        asked.extend(items)
        return json.dumps([{"id": i["id"], "verdict": answers[i["evidence"].split(" = ")[0].split(" (")[0]]} for i in items])
    register_mock("fact_checker", reply)
    return asked


def test_code_decides_assumed_facts_and_unfetched_sources():
    _store()
    asked = _judge({"team_size": "supports", "Config": "supports"})
    card = _card("a:x", facts=["F-01", "F-03"], cites=["src-x-1", "src-x-2", "src-x-3"])
    card.claim = "Keep config in the environment"
    cards, checks, errors = fact_check([card], SHEET, SOURCES, AgentRuntime())
    by_ref = {c.ref: c for c in checks}
    assert len(asked) == 2                                   # the confirmed fact and the fetched page
    assert "Store config in the environment" in asked[1]["evidence"]   # the passage that matches the claim
    assert by_ref["F-01"].verdict == Verdict.verified and by_ref["F-01"].by == "judge"
    assert by_ref["F-03"].verdict == Verdict.unverified and by_ref["F-03"].by == "code"
    assert by_ref["src-x-1"].verdict == Verdict.unverified and "not fetched" in by_ref["src-x-1"].note
    assert by_ref["src-x-2"].verdict == Verdict.verified and by_ref["src-x-2"].by == "judge"
    assert by_ref["src-x-3"].verdict == Verdict.unverified and "too old" in by_ref["src-x-3"].note
    assert cards[0].weight == 6.0 and errors == []           # 3 (PRD fact) + 3 (fetched official docs)


def test_page_that_does_not_cover_the_claim_carries_no_weight():
    _store()
    _judge({"Config": "not_relevant"})
    cards, checks, _ = fact_check([_card("a:x", cites=["src-x-2"])], SHEET, SOURCES, AgentRuntime())
    assert checks[0].verdict == Verdict.unverified and cards[0].weight == 0.0


def test_precedents_are_judged_by_code_and_weighted_by_context():
    prec = {"dec-1": {"kind": "decision_precedent", "subject": "x", "outcome": "selected", "context": 0.5,
                      "is_sample": False, "reviewer_decision": "approve", "project": "P"},
            "dec-2": {"kind": "decision_precedent", "subject": "x", "outcome": "selected", "context": 1.0,
                      "is_sample": True, "reviewer_decision": "sample", "project": "S"},
            "dec-3": {"kind": "decision_precedent", "subject": "x", "outcome": "rejected", "context": 1.0,
                      "is_sample": False, "reviewer_decision": "approve", "project": "Q"}}
    card = _card("a:x").model_copy(update={"citations": [Citation(kind="precedent", ref=r) for r in prec]})
    cards, checks, _ = fact_check([card], SHEET, prec, AgentRuntime())
    by_ref = {c.ref: c for c in checks}
    assert by_ref["dec-1"].verdict == Verdict.verified and by_ref["dec-1"].weight == 1.5   # 3 × 50% context
    assert by_ref["dec-2"].weight == 0.0 and "Sample" in by_ref["dec-2"].note
    assert by_ref["dec-3"].weight == 0.0 and "does not support" in by_ref["dec-3"].note
    assert cards[0].weight == 1.5


def test_weights_follow_verdicts_and_sides():
    _judge({"team_size": "partly_supports", "cloud_provider": "not_relevant"})
    cards, checks, _ = fact_check([_card("a:x", stance="reject", facts=["F-01", "F-02"])], SHEET, SOURCES, AgentRuntime())
    assert {c.ref: c.weight for c in checks} == {"F-01": 1.5, "F-02": 0.0}
    assert all(c.side == "against" for c in checks)
    assert cards[0].weight == 1.5 and summary(checks)["partly_supports"] == 1


def test_contradicted_card_is_removed():
    _judge({"team_size": "contradicts", "cloud_provider": "supports"})
    cards, checks, _ = fact_check([_card("a:x", facts=["F-01", "F-02"])], SHEET, SOURCES, AgentRuntime())
    assert cards[0].removed and cards[0].weight == 0.0
    assert any("Contradicted by F-01" in i for i in cards[0].issues)
    assert next(c for c in checks if c.ref == "F-01").weight is None


def test_missing_judge_answer_is_unverified_and_reasoning_only_flagged():
    register_mock("fact_checker", lambda s, u: "[]")
    cards, checks, _ = fact_check([_card("a:x", facts=["F-01"]), _card("b:y")], SHEET, SOURCES, AgentRuntime())
    assert checks[0].verdict == Verdict.unverified and checks[0].note == "No verdict from the judge"
    assert "Reasoning only: shown, never counted" in cards[1].issues and cards[1].weight == 0.0


def test_judge_failure_does_not_stop_the_round():
    register_mock("fact_checker", lambda s, u: "not json")
    cards, checks, errors = fact_check([_card("a:x", facts=["F-01"])], SHEET, SOURCES, AgentRuntime(max_attempts=1))
    assert errors and checks[0].verdict == Verdict.unverified and cards[0].weight == 0.0


def test_batches_cover_every_item():
    asked = _judge({"team_size": "supports", "cloud_provider": "supports"})
    cards = [_card(f"a:s{i}", facts=["F-01", "F-02"]) for i in range(60)]   # 120 items → 3 batches of 50
    out, checks, _ = fact_check(cards, SHEET, SOURCES, AgentRuntime())
    assert len(asked) == 120 and all(c.verdict == Verdict.verified for c in checks)
    assert all(c.weight == 6.0 for c in out)
