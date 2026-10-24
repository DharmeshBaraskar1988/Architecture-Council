from datetime import datetime, timedelta, timezone

import httpx

from app.catalog import verify
from app.catalog.gate import GateVerdict, gate, swap_plans
from app.knowledge.crawler import Page, page_id

NOW = datetime.now(timezone.utc)


def _page(url, ok=True, title="Overview"):
    return Page(id=page_id(url), url=url, domain="x", ok=ok, title=title, text="x" * 300 if ok else "",
                fetched_at=NOW.isoformat(timespec="seconds"), error=None if ok else "HTTP 403")


def _signals(repo_json=None, hf_json=None):
    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if u.startswith("https://api.github.com/repos/"):
            return httpx.Response(200, json=repo_json)
        if "securityscorecards" in u:
            return httpx.Response(200, json={"score": 7.1})
        if u.startswith("https://huggingface.co/api/models/"):
            return httpx.Response(200, json=hf_json)
        return httpx.Response(404)
    return verify.Signals(httpx.Client(transport=httpx.MockTransport(handler)))


OSS = {"id": "lib", "name": "lib", "type": "open_source", "licence": "MIT", "lifecycle": "ga", "official_api": True,
       "data_terms": "ok", "repo": "o/lib", "pages": {"official": "https://github.com/o/lib", "terms": "https://github.com/o/lib/LICENSE"}}


def test_github_decides_licence_and_maintenance():
    pages = {u: _page(u) for u in OSS["pages"].values()}
    recent = {"license": {"spdx_id": "Apache-2.0"}, "archived": False, "pushed_at": (NOW - timedelta(days=10)).isoformat()}
    v = verify.verify_candidate(OSS, pages, _signals(recent))
    assert v["verified"] and v["overrides"] == {"licence": "Apache-2.0", "maintained": True}
    assert any("differs from GitHub" in n for n in v["notes"])
    assert v["signals"]["github"]["scorecard"] == 7.1
    assert gate(OSS, v).verdict == GateVerdict.production_eligible

    stale = {"license": {"spdx_id": "MIT"}, "archived": False, "pushed_at": (NOW - timedelta(days=500)).isoformat()}
    v = verify.verify_candidate(OSS, pages, _signals(stale))
    r = gate(OSS, v)
    assert r.verdict == GateVerdict.poc_only and any("maintained" in x for x in r.reasons)


def test_old_gpl_ids_from_github_match_the_policy():
    pages = {u: _page(u) for u in OSS["pages"].values()}
    agpl = {"license": {"spdx_id": "AGPL-3.0"}, "archived": False, "pushed_at": NOW.isoformat()}
    c = {**OSS, "licence": "AGPL-3.0-only"}
    v = verify.verify_candidate(c, pages, _signals(agpl))
    assert not any("differs" in n for n in v["notes"])
    assert gate(c, v).verdict == GateVerdict.poc_only


def test_model_licence_comes_from_the_model_card():
    c = {**OSS, "model": "o/model", "licence": "Apache-2.0"}
    pages = {u: _page(u) for u in c["pages"].values()}
    repo = {"license": {"spdx_id": "Apache-2.0"}, "archived": False, "pushed_at": NOW.isoformat()}
    v = verify.verify_candidate(c, pages, _signals(repo, {"cardData": {"license": "llama3.3"}}))
    assert v["overrides"]["licence"] == "llama3.3"
    assert gate(c, v).verdict == GateVerdict.poc_only                  # custom model licence: legal review


def test_missing_page_or_preview_title():
    svc = {"id": "s", "name": "s", "type": "cloud_managed", "licence": "proprietary", "lifecycle": "ga", "sla": True,
           "official_api": True, "data_terms": "ok",
           "pages": {"official": "https://a/o", "pricing": "https://a/p", "terms": "https://a/t", "sla": "https://a/s"}}
    pages = {u: _page(u) for u in svc["pages"].values()}
    pages["https://a/p"] = _page("https://a/p", ok=False)
    v = verify.verify_candidate(svc, pages, _signals())
    assert not v["verified"] and gate(svc, v).verdict == GateVerdict.needs_verification
    pages["https://a/p"] = _page("https://a/p")
    pages["https://a/o"] = _page("https://a/o", title="Avatar API (Preview) - Docs")
    v = verify.verify_candidate(svc, pages, _signals())
    assert v["verified"] and v["overrides"]["lifecycle"] == "preview"
    assert gate(svc, v).verdict == GateVerdict.poc_only


def test_contract_sla_and_owned():
    base = dict(id="x", name="x", lifecycle="ga", official_api=True, data_terms="ok", verified=True, licence="proprietary")
    r = gate({**base, "type": "saas", "sla": "contract"})
    assert r.verdict == GateVerdict.poc_only and "enterprise contract" in r.reasons[0]
    assert gate({"id": "o", "name": "Our Azure", "type": "owned"}).verdict == GateVerdict.production_eligible


def test_swap_plan_prefers_owned_then_same_provider():
    g = {"llm": [{"name": "SaaS LLM", "type": "saas", "provider": "openai", "verdict": "poc_only", "reasons": ["No SLA"]},
                 {"name": "Cloud A", "type": "cloud_managed", "provider": "aws", "verdict": "production_eligible", "reasons": []},
                 {"name": "Owned", "type": "owned", "provider": "azure", "verdict": "production_eligible", "reasons": []}],
         "tts": [{"name": "Only POC", "type": "open_source", "provider": None, "verdict": "poc_only", "reasons": ["AGPL"]}]}
    plans = {p["poc"]: p for p in swap_plans(g)}
    assert plans["SaaS LLM"]["swap_to"] == ["Owned", "Cloud A"]
    assert plans["Only POC"]["swap_to"] == [] and "waits" in plans["Only POC"]["note"]


def test_existing_stack_adds_owned_candidates(tmp_path, monkeypatch):
    import shutil
    from app import config as cfg
    from app.catalog.gate import gate_catalog
    conf = tmp_path / "config"
    shutil.copytree(cfg.CONFIG_DIR, conf)
    (conf / "policies" / "existing_stack.yaml").write_text(
        "owned:\n  - {name: Our Azure EA, provider: azure, capabilities: [llm, hosting]}\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "CONFIG_DIR", conf)
    cfg.config.cache_clear()
    try:
        res = gate_catalog()
        owned = [r for r in res["llm"] if r.type == "owned"]
        assert owned and owned[0].name == "Our Azure EA" and owned[0].verdict == GateVerdict.production_eligible
        assert not [r for r in res["queue"] if r.type == "owned"]
    finally:
        cfg.config.cache_clear()


def test_whole_catalog_meets_the_gate_rules():
    """Every candidate of the real catalog gets a verdict, and nothing preview, non-commercial or
    without an official API is production-eligible (Phase 1 acceptance)."""
    from app.catalog.gate import gate_catalog
    from app.config import load_dir
    raw = {c["id"]: c for cap in load_dir("solutions") for c in cap["candidates"]}
    for rs in gate_catalog().values():
        for r in rs:
            c = raw[r.id]
            if r.verdict == GateVerdict.production_eligible:
                assert c.get("lifecycle") == "ga" and c.get("official_api") is True and c.get("data_terms") == "ok"
