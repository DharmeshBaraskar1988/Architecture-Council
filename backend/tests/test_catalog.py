from pathlib import Path
import json

from app.agents.runtime import AgentRuntime, register_mock
from app.catalog.gate import GateVerdict, gate, gate_catalog
from app.catalog.models import validate_catalogs
from app.catalog.rules import Applicability, shortlist
from app.config import load_yaml
from app.knowledge.factsheet import build_fact_sheet
from app.knowledge.ingest import load_document

FIXTURES = Path(__file__).parent / "fixtures"


def test_catalog_files_are_valid():
    assert validate_catalogs() == []


def test_s1_shortlist_matches_golden():
    fixture = (FIXTURES / "s1_mock_moderator.json").read_text(encoding="utf-8")
    register_mock("moderator", lambda s, u: fixture)
    sheet = build_fact_sheet(load_document(FIXTURES / "s1_financial_briefing.md"), AgentRuntime())
    got = {i.id: i.status for i in shortlist(sheet)}
    exp = load_yaml(FIXTURES / "s1_expected.yaml")["shortlist"]
    for status, ids in exp.items():
        for fid in ids:
            assert got[fid] == Applicability(status), (fid, got[fid], status)


def test_gate_logic():
    base = dict(id="x", name="x", lifecycle="ga", official_api=True, data_terms="ok", verified=True)
    assert gate({**base, "type": "open_source", "licence": "Apache-2.0", "maintained": True}).verdict == GateVerdict.production_eligible
    assert gate({**base, "type": "open_source", "licence": "AGPL-3.0-only", "maintained": True}).verdict == GateVerdict.poc_only
    assert gate({**base, "type": "open_source", "licence": "CC-BY-NC-4.0", "maintained": True}).verdict == GateVerdict.poc_only
    assert gate({**base, "type": "cloud_managed", "licence": "proprietary", "sla": True}).verdict == GateVerdict.production_eligible
    assert gate({**base, "type": "cloud_managed", "licence": "proprietary", "sla": True, "lifecycle": "preview"}).verdict == GateVerdict.poc_only
    assert gate({**base, "type": "saas", "licence": "proprietary", "sla": True, "lifecycle": "deprecated"}).verdict == GateVerdict.rejected
    assert gate({**base, "type": "open_source", "licence": "MIT", "maintained": True, "verified": False}).verdict == GateVerdict.needs_verification
    assert gate({"id": "n", "name": "none", "type": "none"}).verdict == GateVerdict.no_native_service


def test_seed_catalog_gate_results():
    res = {r.id: r.verdict for rs in gate_catalog().values() for r in rs}
    assert res["edge_tts"] == GateVerdict.poc_only          # no official API agreement
    assert res["pymupdf"] == GateVerdict.poc_only           # AGPL needs review
    assert res["aws_avatar"] == GateVerdict.no_native_service
    assert res["kokoro_82m"] == GateVerdict.needs_verification  # not yet verified live
