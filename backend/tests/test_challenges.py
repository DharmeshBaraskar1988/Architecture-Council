import json

from app.debate import challenges
from app.debate.challenges import ChallengeDraft, assign, check_challenges, untested
from app.schemas import ArgumentCard, Fact, FactSheet, FactStatus

AGENTS = ["strategist", "architect", "platform_cost", "critic"]
SHEET = FactSheet(document="t", facts=[Fact(id="F-01", key="team_size", value=6, status=FactStatus.confirmed)])


def _card(agent, subject, stance="adopt", removed=False):
    return ArgumentCard(agent=agent, subject=subject, stance=stance, claim="c", facts=["F-01"],
                        id=f"{agent}:{subject}", removed=removed)


def test_challenger_is_never_on_the_same_provider(monkeypatch):
    prov = {"strategist": "openai", "architect": "openai", "platform_cost": "gemini", "critic": "groq"}
    monkeypatch.setattr(challenges, "provider", lambda a: prov[a])
    cards = [_card(a, f"s{i}") for i, a in enumerate(AGENTS)] * 1
    assigned, notes = assign(cards, AGENTS)
    by_card = {cid: a for a, ids in assigned.items() for cid in ids}
    assert by_card["strategist:s0"] not in ("strategist", "architect")
    assert by_card["architect:s1"] not in ("strategist", "architect")
    assert notes == []


def test_prefers_a_voter_who_disagrees():
    cards = [_card("strategist", "x"), _card("architect", "x"), _card("platform_cost", "x", "reject"), _card("critic", "x")]
    assigned, _ = assign(cards, AGENTS)
    by_card = {cid: a for a, ids in assigned.items() for cid in ids if not cid.startswith("counter:")}
    assert by_card["strategist:x"] == "platform_cost"
    assert by_card["platform_cost:x"] != "platform_cost"


def test_every_live_card_gets_exactly_one_challenger_and_load_is_even():
    cards = [_card(a, f"s{i}") for i in range(6) for a in AGENTS]
    assigned, _ = assign(cards, AGENTS)
    card_targets = [t for ts in assigned.values() for t in ts if not t.startswith("counter:")]
    assert sorted(card_targets) == sorted(c.id for c in cards)
    loads = [sum(not t.startswith("counter:") for t in ts) for ts in assigned.values()]
    assert max(loads) - min(loads) <= 1


def test_counter_case_only_for_unanimous_subjects_and_removed_cards_skipped():
    cards = [_card("strategist", "u"), _card("architect", "u"),                     # unanimous adopt
             _card("strategist", "d"), _card("architect", "d", "reject"),           # disagreement
             _card("strategist", "solo"),                                            # one card: no panel
             _card("critic", "u", removed=True)]
    assigned, _ = assign(cards, AGENTS)
    assert [t for t in assigned["critic"] if t.startswith("counter:")] == ["counter:u"]
    assert "critic:u" not in [t for ts in assigned.values() for t in ts]


def test_check_drops_unassigned_and_duplicates_and_sets_side():
    cards = [_card("architect", "x"), _card("strategist", "y", "reject"), _card("critic", "x")]
    drafts = [ChallengeDraft(target="architect:x", type="cost", text="t", facts=["F-01"]),
              ChallengeDraft(target="architect:x", type="fact", text="again"),
              ChallengeDraft(target="strategist:y", type="relevance", text="t", facts=["F-01"]),
              ChallengeDraft(target="counter:x", type="alternative", text="t", facts=["F-99"]),
              ChallengeDraft(target="critic:x", type="cost", text="not mine")]
    kept, dropped = check_challenges("platform_cost", drafts, ["architect:x", "strategist:y", "counter:x"],
                                     cards, SHEET, {})
    by = {c.target: c for c in kept}
    assert by["architect:x"].side == "against" and by["architect:x"].type.value == "cost"
    assert by["strategist:y"].side == "for"                  # challenging a reject pushes the subject forward
    assert by["counter:x"].counter_case and by["counter:x"].target_agent == ""
    assert any("F-99" in i for i in by["counter:x"].issues)
    assert {d["reason"] for d in dropped} == {"Second challenge on the same target", "Not one of this agent's targets"}


def test_untested_subjects():
    cards = [_card("architect", "x"), _card("architect", "y")]
    kept, _ = check_challenges("critic", [ChallengeDraft(target="architect:x", type="cost", text="t")],
                               ["architect:x", "architect:y"], cards, SHEET, {})
    assert untested(cards, kept) == ["y"]


def test_r4_in_the_graph(tmp_path):
    from test_proposals import S1, _graph
    from app.orchestrator import graph as g

    graph, bus, _ = _graph(tmp_path)
    paused = g.start(graph, "r4", S1, str(tmp_path))
    saved = json.loads((tmp_path / "challenges.json").read_text(encoding="utf-8"))
    live = [c for c in paused["state"]["cards"] if not c["removed"]]
    assert {c["target"] for c in saved["challenges"] if not c["counter_case"]} == {c["id"] for c in live}
    assert saved["untested_subjects"] == [] and saved["unanswered"] == []
    assert sum(e.type == "challenge.raised" for e in bus.events) == len(saved["challenges"])
    assert all(c["weight"] is not None for c in saved["challenges"])
    assert "R4 challenges" not in paused["for_reviewer"]["pending_rounds"]
