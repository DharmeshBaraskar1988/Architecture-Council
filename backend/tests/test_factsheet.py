from pathlib import Path
import json

from app.agents.runtime import AgentRuntime, register_mock
from app.events.bus import EventBus
from app.knowledge.factsheet import build_fact_sheet
from app.knowledge.ingest import load_document
from app.schemas import FactStatus

FIXTURES = Path(__file__).parent / "fixtures"

S1 = FIXTURES / "s1_financial_briefing.md"


def test_golden_s1_fact_sheet_all_quotes_verify():
    fixture = (FIXTURES / "s1_mock_moderator.json").read_text(encoding="utf-8")
    register_mock("moderator", lambda s, u: fixture)
    sheet = build_fact_sheet(load_document(S1), AgentRuntime())
    by = {f.key: f for f in sheet.facts}
    stated = [f for f in sheet.facts if f.status != FactStatus.assumed]
    assert all(f.status == FactStatus.confirmed for f in stated), [(f.key, f.note) for f in stated if f.status != FactStatus.confirmed]
    assert by["card_payments"].status == FactStatus.assumed
    assert by["team_size"].value == 5 and by["cloud_provider"].value == "azure"


def test_invented_quote_is_unverified_and_unknown_keys_dropped():
    reply = [
        {"key": "team_size", "value": "12", "quote": "The team has twelve engineers.", "page": 2},
        {"key": "favourite_colour", "value": "blue", "quote": "blue", "page": 1},
        {"key": "containerised", "value": "yes", "quote": "Services are packaged as containers", "page": 1},
    ]
    register_mock("moderator", lambda s, u: json.dumps(reply))
    bus = EventBus("t")
    sheet = build_fact_sheet(load_document(S1), AgentRuntime(), bus)
    by = {f.key: f for f in sheet.facts}
    assert "favourite_colour" not in by
    assert by["team_size"].status == FactStatus.unverified and by["team_size"].value == 12
    assert by["containerised"].status == FactStatus.confirmed and by["containerised"].value is True
    assert by["containerised"].page == 4 and "corrected" in by["containerised"].note
    assert bus.events[-1].type == "factsheet.ready"


def test_a_quote_that_does_not_state_the_fact_becomes_an_assumption():
    quote = "Video rendering can take several minutes, so jobs run in the background and users are notified when they finish."
    reply = [{"key": "independent_scaling_need", "value": True, "quote": quote, "page": 3},
             {"key": "async_workflows", "value": True, "quote": quote, "page": 3}]
    register_mock("moderator", lambda s, u: json.dumps(reply))
    sheet = build_fact_sheet(load_document(FIXTURES / "s1_financial_briefing.md"), AgentRuntime())
    by = {f.key: f for f in sheet.facts}
    assert by["async_workflows"].status == FactStatus.confirmed
    assert by["independent_scaling_need"].status == FactStatus.assumed and "does not mention" in by["independent_scaling_need"].note
