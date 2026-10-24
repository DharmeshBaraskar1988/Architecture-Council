import json

from app.debate.rebuttals import RebuttalDraft, apply, assign, check_rebuttals, responder, unanswered
from app.schemas import ArgumentCard, Challenge, Fact, FactSheet, FactStatus, Rebuttal

AGENTS = ["strategist", "architect", "platform_cost", "critic"]
SHEET = FactSheet(document="t", facts=[Fact(id="F-01", key="team_size", value=6, status=FactStatus.confirmed)])


def _card(agent, subject, stance="adopt", weight=3.0, removed=False):
    return ArgumentCard(agent=agent, subject=subject, stance=stance, claim="c", facts=["F-01"],
                        id=f"{agent}:{subject}", weight=weight, removed=removed)


def _ch(by, target, subject, side="against", counter=False, removed=False):
    return Challenge(agent=by, target_subject=subject, target_agent="" if counter else target.split(":")[0],
                     type="cost", text="t", id=f"{by}>{target}", target=target, side=side,
                     counter_case=counter, removed=removed, weight=3.0)


def test_author_answers_and_counter_case_goes_to_strongest_card():
    cards = [_card("strategist", "x", weight=3.0), _card("architect", "x", weight=9.0),
             _card("platform_cost", "x", weight=12.0, removed=True)]       # removed card cannot answer
    assert responder(_ch("critic", "strategist:x", "x"), cards, AGENTS) == "strategist"
    assert responder(_ch("critic", "counter:x", "x", counter=True), cards, AGENTS) == "architect"
    # the challenger never answers its own counter-case, even with the strongest card
    assert responder(_ch("architect", "counter:x", "x", counter=True), cards, AGENTS) == "strategist"


def test_removed_challenges_need_no_answer():
    cards = [_card("architect", "x")]
    assigned = assign([_ch("critic", "architect:x", "x", removed=True)], cards, AGENTS)
    assert all(ids == [] for ids in assigned.values())


def test_check_sets_side_and_drops_strays():
    chs = [_ch("critic", "architect:x", "x"), _ch("critic", "architect:y", "y", side="for")]
    drafts = [RebuttalDraft(challenge="critic>architect:x", response="rebut", text="t", facts=["F-01", "F-99"]),
              RebuttalDraft(challenge="critic>architect:x", response="concede", text="again"),
              RebuttalDraft(challenge="critic>architect:y", response="concede", text="ok", facts=["F-01"]),
              RebuttalDraft(challenge="someone>else", response="rebut", text="t")]
    kept, dropped = check_rebuttals("architect", drafts, ["critic>architect:x", "critic>architect:y"], chs, SHEET, {})
    by = {r.challenge: r for r in kept}
    assert by["critic>architect:x"].side == "for" and by["critic>architect:x"].facts == ["F-01"]
    assert any("F-99" in i for i in by["critic>architect:x"].issues)
    assert by["critic>architect:y"].side == "against" and by["critic>architect:y"].facts == []   # concessions cite nothing
    assert len(dropped) == 2


def test_only_weighted_rebuttals_answer_and_concessions_withdraw_cards():
    cards = [_card("architect", "x"), _card("architect", "y"), _card("architect", "z")]
    chs = [_ch("critic", "architect:x", "x"), _ch("critic", "architect:y", "y"), _ch("critic", "architect:z", "z"),
           _ch("critic", "counter:x", "x", counter=True)]

    def r(ch, response, weight):
        return Rebuttal(agent="architect", challenge=ch.id, target=ch.target, subject=ch.target_subject,
                        response=response, text="t", weight=weight, id=f"re:{ch.id}")
    rebs = [r(chs[0], "rebut", 3.0), r(chs[1], "rebut", 0.0), r(chs[2], "concede", None), r(chs[3], "concede", None)]
    new_cards, new_chs = apply(cards, chs, rebs)
    assert [c.answered for c in new_chs] == [True, False, False, False]
    assert [c.conceded for c in new_cards] == [False, False, True]       # counter-case concession withdraws no card


def test_unanswered_lists_missing_and_failed():
    out = unanswered({"architect": ["a", "b"], "critic": ["c"]},
                     [Rebuttal(agent="architect", challenge="a", target="t", subject="s", response="rebut", text="t")],
                     {"critic"})
    assert out == [{"agent": "architect", "challenge": "b", "reason": "no answer written"},
                   {"agent": "critic", "challenge": "c", "reason": "author failed"}]


def test_r5_in_the_graph(tmp_path):
    from test_proposals import S1, _graph
    from app.orchestrator import graph as g

    graph, bus, _ = _graph(tmp_path)
    paused = g.start(graph, "r5", S1, str(tmp_path))
    saved = json.loads((tmp_path / "rebuttals.json").read_text(encoding="utf-8"))
    live = [c for c in paused["state"]["challenges"] if not c["removed"]]
    assert {r["challenge"] for r in saved["rebuttals"]} == {c["id"] for c in live}
    assert saved["unanswered"] == [] and saved["failures"] == []
    assert sum(e.type == "rebuttal.made" for e in bus.events) == len(saved["rebuttals"])
    assert "R5 rebuttals" not in paused["for_reviewer"]["pending_rounds"]


def test_lead_subjects_are_revised_never_withdrawn():
    cards = [_card("strategist", "build_approach"), _card("architect", "x")]
    chs = [_ch("platform_cost", "strategist:build_approach", "build_approach"), _ch("critic", "architect:x", "x")]
    drafts = [RebuttalDraft(challenge="platform_cost>strategist:build_approach", response="concede",
                            text="Fair: self-host the cheap parts.", revised_claim="Assemble: pgvector and Docling self-hosted.")]
    kept, _ = check_rebuttals("strategist", drafts, ["platform_cost>strategist:build_approach"], chs, SHEET, {})
    assert kept[0].response == "revise" and kept[0].revised_claim == "Assemble: pgvector and Docling self-hosted."
    stray = [RebuttalDraft(challenge="critic>architect:x", response="revise", text="t", revised_claim="new")]
    other, _ = check_rebuttals("architect", stray, ["critic>architect:x"], chs, SHEET, {})
    assert other[0].response == "concede"                     # only lead subjects can be revised
    new_cards, new_chs = apply(cards, chs, kept + other)
    lead = next(c for c in new_cards if c.subject == "build_approach")
    assert not lead.conceded and lead.claim == "Assemble: pgvector and Docling self-hosted."
    assert any("Revised in R5" in i for i in lead.issues)
    assert next(c for c in new_chs if c.target_subject == "build_approach").answered
    assert next(c for c in new_cards if c.subject == "x").conceded
