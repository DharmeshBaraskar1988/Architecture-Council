import json

from app.ledger import store

FACTS = [{"key": "cloud_provider", "value": "azure", "status": "confirmed"},
         {"key": "personal_data", "value": True, "status": "confirmed"},
         {"key": "users_in_india", "value": True, "status": "confirmed"},
         {"key": "financial_documents", "value": True, "status": "confirmed"},
         {"key": "async_workflows", "value": True, "status": "confirmed"},
         {"key": "team_size", "value": 8, "status": "confirmed"},
         {"key": "users_in_eu", "value": False, "status": "assumed"}]       # assumed facts are not context


def test_context_profile_and_match():
    ctx = store.context(FACTS)
    assert ctx["team_size"] == 1 and "users_in_eu" not in ctx            # 8 people: band 6-15
    assert store.context_match(ctx, ctx) == 1.0
    other = {**ctx, "cloud_provider": "aws"}
    assert round(store.context_match(ctx, other), 2) == round(5 / 6, 2)
    assert store.context_match({}, {}) == 0.0


def test_samples_are_marked_and_searchable():
    n = store.seed_samples()
    assert n >= 6 and store.seed_samples() == n                          # idempotent
    found = store.search(FACTS, subject="azure_waf")
    assert found and found[0]["is_sample"] and found[0]["context_match"] == 100
    idx = store.precedent_index(FACTS, ["azure_waf", "microservices_first"])
    assert all(p["is_sample"] and p["title"].startswith("SAMPLE") for p in idx.values())


def _signed_run(tmp_path, decision="approve"):
    d = tmp_path / "20260101-000000-abcd"
    d.mkdir()
    (d / "fact_sheet.json").write_text(json.dumps({"document": "prd.md", "facts": FACTS}), encoding="utf-8")
    (d / "strategy_decision.json").write_text(json.dumps({"stage": "strategy", "board": [
        {"subject": "azure_waf", "name": "Azure WAF", "outcome": "selected", "agreement": 81, "vote_support": 80,
         "evidence_balance": 83, "reasons": ["Vote 80%"], "guardrail": None},
        {"subject": "atam", "name": "ATAM", "outcome": "rejected", "agreement": 30, "reasons": [], "guardrail": None}]}),
        encoding="utf-8")
    return d


def test_nothing_is_recorded_before_sign_off_then_everything_is(tmp_path):
    d = _signed_run(tmp_path)
    assert store.record_run(d) == []
    (d / "review.json").write_text(json.dumps({"decision": "approve", "reviewer": "you"}), encoding="utf-8")
    ids = store.record_run(d)
    assert ids == [f"dec-{d.name}-azure_waf", f"dec-{d.name}-atam"]
    assert store.record_run(d) == ids and len(store.all_decisions()) == 2        # safe to run twice
    hit = store.search(FACTS, subject="azure_waf")[0]
    assert hit["context_match"] == 100 and not hit["is_sample"] and hit["reviewer_decision"] == "approve"
    assert store.search(FACTS, subject="azure_waf", exclude_session=d.name) == []   # a run never cites itself


def test_a_document_never_cites_its_own_earlier_runs(tmp_path):
    d = _signed_run(tmp_path)
    (d / "review.json").write_text(json.dumps({"decision": "approve"}), encoding="utf-8")
    store.record_run(d)
    assert store.precedent_index(FACTS, ["azure_waf"], project="prd.md") == {}
    assert store.precedent_index(FACTS, ["azure_waf"], project="other.md")
