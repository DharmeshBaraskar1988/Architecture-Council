from pathlib import Path
import json

from app.agents.runtime import AgentRuntime, register_mock
from app.debate import proposals
from app.debate.proposals import CardDraft, check_cards
from app.events.bus import EventBus
from app.orchestrator import graph as g
from app.schemas import Fact, FactSheet, FactStatus

FIXTURES = Path(__file__).parent / "fixtures"

S1 = str(FIXTURES / "s1_financial_briefing.md")
SHEET = FactSheet(document="t", facts=[
    Fact(id="F-01", key="team_size", value=6, status=FactStatus.confirmed),
    Fact(id="F-02", key="independent_scaling_need", value=False, status=FactStatus.assumed),
])
SHORTLIST = [{"id": "evolutionary_architecture", "status": "candidate"},
             {"id": "dpdp_india", "status": "binding"},
             {"id": "pci_dss", "status": "not_applicable"}]
SOURCES = {"src-evolutionary_architecture-1": {"framework": "evolutionary_architecture"}}


def _card(**kw):
    base = {"subject": "evolutionary_architecture", "stance": "adopt", "claim": "c", "facts": ["F-01"]}
    return CardDraft.model_validate({**base, **kw})


def test_clean_card_has_no_issues():
    kept, dropped = check_cards("architect", [_card(citations=[{"kind": "source", "ref": "src-evolutionary_architecture-1"}])],
                                SHEET, SHORTLIST, SOURCES)
    assert dropped == [] and kept[0].issues == [] and kept[0].id == "architect:evolutionary_architecture"
    assert len(kept[0].citations) == 1


def test_invented_ids_are_removed_and_flagged():
    kept, _ = check_cards("critic", [_card(facts=["F-99"], citations=[{"kind": "source", "ref": "src-made-up"}])],
                          SHEET, SHORTLIST, SOURCES)
    c = kept[0]
    assert c.facts == [] and c.citations == []
    assert any("F-99" in i for i in c.issues)
    assert any("src-made-up" in i for i in c.issues)
    assert "No fact cited: carries no weight" in c.issues


def test_assumed_only_and_binding_reject_are_flagged():
    kept, _ = check_cards("critic", [_card(facts=["F-02"]), _card(subject="dpdp_india", stance="reject")],
                          SHEET, SHORTLIST, SOURCES)
    assert "Rests only on assumed or unverified facts" in kept[0].issues
    assert "Binding framework cannot be rejected" in kept[1].issues


def test_off_shortlist_duplicate_and_lead_only_cards_are_dropped():
    drafts = [_card(), _card(), _card(subject="pci_dss"), _card(subject="build_approach")]
    kept, dropped = check_cards("architect", drafts, SHEET, SHORTLIST, SOURCES)
    assert [c.subject for c in kept] == ["evolutionary_architecture"]
    assert len(dropped) == 3
    kept, dropped = check_cards("strategist", [_card(subject="build_approach")], SHEET, SHORTLIST, SOURCES)
    assert kept[0].subject == "build_approach" and dropped == []


def test_subject_given_by_name_maps_to_id():
    shortlist = [{"id": "c4_model", "name": "C4 model", "status": "candidate"}]
    kept, dropped = check_cards("architect", [_card(subject="C4 Model")], SHEET, shortlist, SOURCES)
    assert dropped == [] and kept[0].subject == "c4_model"


def test_condition_required():
    kept, _ = check_cards("architect", [_card(stance="adopt_with_condition")], SHEET, SHORTLIST, SOURCES)
    assert "Condition missing for adopt_with_condition" in kept[0].issues


def _graph(tmp_path, failing=()):
    register_mock("moderator", lambda s, u: (FIXTURES / "s1_mock_moderator.json").read_text(encoding="utf-8"))
    cards = json.loads((FIXTURES / "s1_mock_proposals.json").read_text(encoding="utf-8"))
    briefs = {}
    for agent, agent_cards in cards.items():
        if agent in failing:
            continue

        def reply(s, u, a=agent, c=agent_cards):
            marker = "\nBALLOT\n" if "\nBALLOT\n" in u else "\nREVOTE\n" if "\nREVOTE\n" in u else None
            if marker:                                       # R6 and R7 re-vote: adopt, convinced by the first item
                items = json.loads(u.split(marker, 1)[1])
                return json.dumps([{"subject": b["subject"], "stance": "adopt", "confidence": 3,
                                    "convinced_by": (b["cards"] or b["withdrawn"])[0]["id"]} for b in items])
            if "CHALLENGES TO YOUR CARDS" in u:              # R5: rebut every challenge with fact F-01
                items = json.loads(u.split("CHALLENGES TO YOUR CARDS\n", 1)[1])
                return json.dumps([{"challenge": i["challenge"], "response": "rebut", "text": "t", "facts": ["F-01"]}
                                   for i in items])
            if "YOUR TARGETS" in u:                         # R4: one evidence challenge per target
                targets = json.loads(u.split("YOUR TARGETS\n", 1)[1])
                return json.dumps([{"target": t["id"], "type": "evidence", "text": "t", "facts": ["F-02"]} for t in targets])
            briefs[a] = u
            return json.dumps(c)
        register_mock(agent, reply)
    register_mock("fact_checker", lambda s, u: json.dumps([{"id": i["id"], "verdict": "supports"} for i in json.loads(u)]))
    bus = EventBus("t", tmp_path / "debate_log.jsonl")
    return g.build_stage0_graph(AgentRuntime(max_attempts=1), bus), bus, briefs


def test_r2_runs_every_voter_blind(tmp_path):
    graph, bus, briefs = _graph(tmp_path)
    paused = g.start(graph, "r2", S1, str(tmp_path))
    assert set(briefs) == set(proposals.voters())
    assert len(set(briefs.values())) == 1                 # identical brief: nobody sees another's cards
    assert "claim" not in next(iter(briefs.values()))
    cards = paused["state"]["cards"]
    assert {c["agent"] for c in cards} == set(proposals.voters())
    assert sum(e.type == "card.proposed" for e in bus.events) == len(cards)
    saved = json.loads((tmp_path / "proposals.json").read_text(encoding="utf-8"))
    assert saved["missing"] == [] and saved["failures"] == []
    assert (tmp_path / "solution_gate.json").exists()
    assert "R2 proposals" not in paused["for_reviewer"]["pending_rounds"]
    # R3 ran on the same cards: one verdict event per citation, factcheck.json written
    fc = json.loads((tmp_path / "factcheck.json").read_text(encoding="utf-8"))
    card_verdicts = [e for e in bus.events if e.type == "factcheck.verdict" and ">" not in e.payload["card"]]
    assert len(card_verdicts) == len(fc["checks"]) > 0     # R4 challenge verdicts carry ids like "a>b:x"
    assert all(c["weight"] is not None for c in paused["state"]["cards"])
    assert paused["for_reviewer"]["verdicts"]["unverified"] > 0           # sources not fetched yet


def test_r2_continues_when_one_voter_fails(tmp_path):
    graph, bus, _ = _graph(tmp_path, failing=("critic",))
    paused = g.start(graph, "r2f", S1, str(tmp_path))
    assert paused["paused_at"] == ["reviewer_gate"]
    assert paused["for_reviewer"]["r2_failures"] == ["critic"]
    assert paused["for_reviewer"]["cards"]["critic"] == 0
    assert any(e.type == "error" and e.payload["agent"] == "critic" for e in bus.events)
