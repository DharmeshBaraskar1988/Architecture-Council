import json

from app.debate.votes import VoteDraft, abstentions, ballot, check_votes, tally
from app.schemas import ArgumentCard, Challenge, Rebuttal

SHORTLIST = [{"id": "x", "status": "candidate"}, {"id": "pci", "status": "binding"},
             {"id": "gdpr", "status": "not_applicable"}]


def _card(agent, subject, stance="adopt", **kw):
    return ArgumentCard(agent=agent, subject=subject, stance=stance, claim="c", id=f"{agent}:{subject}", weight=3.0, **kw)


def _items():
    cards = [_card("architect", "x"), _card("critic", "x", "reject", conceded=True),
             _card("strategist", "pci"), _card("strategist", "build_approach")]
    chs = [Challenge(agent="critic", target_subject="x", target_agent="architect", type="cost", text="t",
                     id="critic>architect:x", target="architect:x", weight=3.0),
           Challenge(agent="critic", target_subject="x", target_agent="architect", type="fact", text="gone",
                     id="critic>gone", target="architect:x", removed=True)]
    rebs = [Rebuttal(agent="architect", challenge="critic>architect:x", target="architect:x", subject="x",
                     response="rebut", text="r", id="re:critic>architect:x", weight=3.0)]
    return ballot(SHORTLIST, cards, chs, rebs)


def test_ballot_has_open_and_lead_subjects_and_hides_nothing_that_survived():
    items = _items()
    assert [b["subject"] for b in items] == ["x", "pci", "build_approach"]   # not_applicable is not voted on
    x = items[0]
    assert [c["id"] for c in x["cards"]] == ["architect:x"]
    assert x["withdrawn"] == [{"id": "critic:x", "why": "conceded"}]
    assert [c["id"] for c in x["challenges"]] == ["critic>architect:x"]       # removed challenge left out
    assert x["rebuttals"][0]["id"] == "re:critic>architect:x"
    assert "votes" not in json.dumps(items)                                   # blind: no votes on the ballot


def test_vote_checks():
    drafts = [VoteDraft(subject="x", stance="adopt", confidence=4, convinced_by="re:critic>architect:x"),
              VoteDraft(subject="x", stance="reject", confidence=1, convinced_by="architect:x"),
              VoteDraft(subject="pci", stance="adopt_with_condition", confidence=3, convinced_by="made-up"),
              VoteDraft(subject="gdpr", stance="adopt", confidence=5, convinced_by="x")]
    kept, dropped = check_votes("platform_cost", drafts, _items())
    assert [v.subject for v in kept] == ["x", "pci"]
    assert kept[0].issues == []
    assert "Condition missing for adopt_with_condition" in kept[1].issues
    assert any("made-up" in i for i in kept[1].issues)
    assert {d["reason"] for d in dropped} == {"Second vote on the same subject", "Not on the ballot"}


def test_abstentions_and_tally():
    items = _items()
    kept, _ = check_votes("architect", [VoteDraft(subject="x", stance="adopt", confidence=4, convinced_by="architect:x")], items)
    ab = abstentions(kept, items, ["architect", "critic"], {"critic"})
    assert {"agent": "architect", "subject": "pci", "reason": "no vote cast"} in ab
    assert sum(a["agent"] == "critic" and a["reason"] == "voter failed" for a in ab) == 3
    assert tally(kept, items)["x"] == {"adopt": 1, "adopt_with_condition": 0, "reject": 0}


def test_r6_in_the_graph(tmp_path):
    from test_proposals import S1, _graph
    from app.debate import proposals
    from app.orchestrator import graph as g

    graph, bus, _ = _graph(tmp_path)
    paused = g.start(graph, "r6", S1, str(tmp_path))
    saved = json.loads((tmp_path / "votes.json").read_text(encoding="utf-8"))
    n_subjects = len(saved["ballot"])
    assert n_subjects > 0 and len(saved["votes"]) == n_subjects * len(proposals.voters())
    assert saved["abstentions"] == [] and saved["failures"] == []
    assert sum(e.type == "vote.cast" for e in bus.events) == len(saved["votes"])
    assert paused["for_reviewer"]["pending_rounds"] == []
