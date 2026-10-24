"""Golden runs and evals (task 1.19): checks every Phase 1 acceptance criterion on real run folders.

    council evals --runs 3                  run S1, S2 and S3 three times each, live, then report
    council evals --from ID ID ...          report on runs that already exist

Every number in the report is read from the run files (fact_sheet.json, applicability.json,
proposals.json, factcheck.json, challenges.json, strategy_decision.json, usage.json, debate_log.jsonl),
so a criterion can be traced to the event behind it. Golden runs are auto-approved into a separate
database (data/evals/council_evals.db), so test runs never become precedents for real sessions.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import REPO_ROOT, data_dir, load_yaml

FIXTURES = REPO_ROOT / "backend" / "tests" / "fixtures"
SAMPLES = {
    "s1": (REPO_ROOT / "data" / "samples" / "prds" / "s1_financial_briefing.md", FIXTURES / "s1_expected.yaml"),
    "s2": (REPO_ROOT / "data" / "samples" / "prds" / "s2_shopsphere.md", FIXTURES / "s2_expected.yaml"),
    "s3": (REPO_ROOT / "data" / "samples" / "prds" / "s3_movewell_clinics.docx", FIXTURES / "s3_expected.yaml"),
}
CLEAR_HIGH, CLEAR_LOW = 75.0, 40.0
MAX_SECONDS = 300


def _json(d: Path, name: str, default=None):
    p = d / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def sample_of(d: Path) -> Optional[str]:
    doc = (_json(d, "fact_sheet.json") or {}).get("document", "")
    return next((s for s, (prd, _) in SAMPLES.items() if prd.name == doc), None)


def check_run(d: Path, expected: dict) -> dict:
    """All per-run criteria. Each entry: ok (bool) and the numbers behind it."""
    sheet = _json(d, "fact_sheet.json", {"facts": []})
    facts = {f["key"]: f for f in sheet["facts"]}
    out: dict = {"run": d.name}

    stated = [f for f in sheet["facts"] if f["status"] in ("confirmed", "unverified")]
    passed = sum(f["status"] == "confirmed" for f in stated)
    rate = 100 * passed / len(stated) if stated else 0
    out["quote_match"] = {"ok": rate >= 90, "pct": round(rate), "confirmed": passed, "stated": len(stated)}

    fe = expected.get("fact_sheet", {})
    wrong = [k for k in fe.get("must_confirm", []) if facts.get(k, {}).get("status") != "confirmed"]
    wrong += [f"{k}={facts.get(k, {}).get('value')!r} (want {v!r})" for k, v in fe.get("values", {}).items()
              if facts.get(k, {}).get("value") != v]
    wrong += [f"{k} is true" for k in fe.get("must_not_be_true", []) if facts.get(k, {}).get("value") is True]
    out["fact_expectations"] = {"ok": not wrong, "misses": wrong}

    items = _json(d, "applicability.json", [])
    short = {i["id"]: i["status"] for i in items}
    parked = {r["subject"] for r in (_json(d, "strategy_decision.json") or {}).get("board", []) if r["outcome"] == "parked"}
    for i in items:                      # an assumption never decides: parked for the reviewer counts as right
        if i["id"] in expected.get("parked_if_assumed", []) and i.get("depends_on_assumption") and i["id"] in parked:
            short[i["id"]] = "not_applicable"
    exp_short = expected.get("shortlist", {})
    binding_missing = [f for f in exp_short.get("binding", []) if short.get(f) != "binding"]
    out["binding_found"] = {"ok": not binding_missing, "missing": binding_missing}
    off = [f"{f}: {short.get(f)} (want {st})" for st, ids in exp_short.items() for f in ids if short.get(f) != st]
    out["shortlist"] = {"ok": not off, "differences": off}

    dec = _json(d, "strategy_decision.json")
    if not dec:
        out["finished"] = {"ok": False}
        return out
    out["finished"] = {"ok": True}
    board = {r["subject"]: r for r in dec["board"]}
    challenges = (_json(d, "challenges.json") or {}).get("challenges", [])
    open_fw = [s for s, st in short.items() if st == "candidate"]
    challenged = {c["target_subject"] for c in challenges if not c.get("removed")}
    unchallenged = [s for s in open_fw if s not in challenged]
    out["every_framework_challenged"] = {"ok": not unchallenged, "unchallenged": unchallenged}

    cards = (_json(d, "proposals.json") or {}).get("cards", [])
    checks = (_json(d, "factcheck.json") or {}).get("checks", [])
    checked = {(c["card"], c["ref"]) for c in checks}
    cited = {(c["id"], ref) for c in cards for ref in c["facts"] + [x["ref"] for x in c["citations"]]}
    out["verdict_on_every_citation"] = {"ok": cited <= checked, "citations": len(cited), "missing": len(cited - checked)}

    no_numbers = [s for s, r in board.items() if r["outcome"] not in ("selected", "parked", "not_applicable")
                  and (r.get("agreement") is None or r.get("vote_support") is None or r.get("evidence_balance") is None)]
    out["v_e_a_outcome"] = {"ok": not no_numbers, "missing": no_numbers}

    all_checks = checks + (_json(d, "challenges.json") or {}).get("checks", []) + (_json(d, "rebuttals.json") or {}).get("checks", [])
    weighted_bad = [f"{c['card']}#{c['ref']}" for c in all_checks
                    if c["verdict"] in ("unverified", "contradicted") and (c.get("weight") or 0) > 0]
    out["no_unverified_weighted"] = {"ok": not weighted_bad, "bad": weighted_bad,
                                     "verdicts": {v: sum(c["verdict"] == v for c in all_checks)
                                                  for v in ("verified", "partly_supports", "unverified", "contradicted")}}

    out["statement_and_adr"] = {"ok": bool(dec.get("statement")) and (d / "strategy_adr.md").exists()}
    review = _json(d, "review.json")
    out["signed_record"] = {"ok": bool(review), "decision": (review or {}).get("decision")}
    if review:
        from app.ledger import store
        with __import__("contextlib").closing(store.connect()) as con:
            n = con.execute("SELECT COUNT(*) FROM decisions WHERE session_id = ?", (d.name,)).fetchone()[0]
        out["signed_record"].update(ok=n == len(board), rows=n)

    lead = [s for s in ("build_approach", "delivery_path") if s not in board]
    plans = _json(d, "swap_plans.json", [])
    no_swap = [f"{p['capability']}: {p['poc']}" for p in plans if not p["swap_to"]]
    out["build_delivery_swap"] = {"ok": not lead and not no_swap, "missing_subjects": lead, "poc_without_swap": no_swap}

    times = [json.loads(ln)["at"] for ln in (d / "debate_log.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    stop = next((json.loads(ln)["at"] for ln in (d / "debate_log.jsonl").read_text(encoding="utf-8").splitlines()
                 if ln.strip() and json.loads(ln)["type"] == "stage.decided"), times[-1])
    secs = (datetime.fromisoformat(stop) - datetime.fromisoformat(times[0])).total_seconds()
    usage = _json(d, "usage.json", {})
    out["time_and_cost"] = {"ok": secs < MAX_SECONDS, "seconds": round(secs), "cost_usd": round(usage.get("cost_usd", 0), 3),
                            "calls": usage.get("calls"), "failed_calls": usage.get("failed")}
    out["outcomes"] = {s: {"outcome": r["outcome"], "agreement": r.get("agreement"),
                           "binding": short.get(s) == "binding"} for s, r in board.items()}
    return out


def stability(runs: list[dict]) -> dict:
    """Same PRD, several runs: every subject that was binding or clear (A ≥ 75% or < 40%) in any run
    must have the same outcome in every run."""
    if len(runs) < 2:
        return {"ok": None, "note": "needs at least 2 runs"}
    subjects = set().union(*(r.get("outcomes", {}).keys() for r in runs))
    unstable, clear = [], []
    for s in sorted(subjects):
        rows = [r.get("outcomes", {}).get(s) for r in runs]
        is_clear = any(x and (x["binding"] or (x["agreement"] is not None and
                                               (x["agreement"] >= CLEAR_HIGH or x["agreement"] < CLEAR_LOW))) for x in rows)
        if not is_clear:
            continue
        clear.append(s)
        if len({x["outcome"] if x else None for x in rows}) > 1:
            unstable.append(f"{s}: " + " / ".join(f"{x['outcome']} {x['agreement']}" if x else "missing" for x in rows))
    return {"ok": not unstable, "clear_subjects": clear, "unstable": unstable}


def gate_summary() -> dict:
    from app.catalog.gate import gate_catalog
    from app.config import load_dir
    raw = {c["id"]: c for cap in load_dir("solutions") for c in cap["candidates"]}
    rows = [r for rs in gate_catalog().values() for r in rs]
    final = {"production_eligible", "poc_only", "rejected", "no_native_service"}
    no_final = [r.id for r in rows if r.verdict.value not in final]
    no_evidence = [r.id for r in rows if r.verdict.value in ("production_eligible", "poc_only", "rejected") and not r.evidence]
    bad_eligible = [r.id for r in rows if r.verdict.value == "production_eligible" and r.type != "owned" and
                    (raw[r.id].get("lifecycle") != "ga" or raw[r.id].get("official_api") is not True)]
    counts = defaultdict(int)
    for r in rows:
        counts[r.verdict.value] += 1
    return {"ok": not no_final and not no_evidence and not bad_eligible, "candidates": len(rows), "counts": dict(counts),
            "not_final": no_final, "no_evidence_links": no_evidence, "wrongly_eligible": bad_eligible}


def report(run_dirs: list[Path]) -> tuple[str, dict]:
    by_sample: dict[str, list[dict]] = defaultdict(list)
    for d in run_dirs:
        s = sample_of(d)
        if s:
            by_sample[s].append(check_run(d, load_yaml(SAMPLES[s][1])))
    gate = gate_summary()
    crit = ["quote_match", "fact_expectations", "binding_found", "shortlist", "finished", "every_framework_challenged",
            "verdict_on_every_citation", "v_e_a_outcome", "no_unverified_weighted", "statement_and_adr",
            "signed_record", "build_delivery_swap", "time_and_cost"]
    names = {"quote_match": "Fact quotes pass the exact-quote check (≥ 90%)", "fact_expectations": "Key facts as expected",
             "binding_found": "Binding frameworks found", "shortlist": "Shortlist matches the golden result",
             "finished": "Run reached a decision", "every_framework_challenged": "Every open framework challenged",
             "verdict_on_every_citation": "A verdict on every citation", "v_e_a_outcome": "V, E, A and an outcome by the rules",
             "no_unverified_weighted": "No unverified or invented citation weighted",
             "statement_and_adr": "Position statement and ADR", "signed_record": "Decision record saved after sign-off",
             "build_delivery_swap": "Build approach, delivery path, swap plan for every POC part",
             "time_and_cost": "Under 5 minutes; cost measured"}
    summary = {"samples": {}, "gate": gate}
    lines = ["# Phase 1 evals report", "", f"Generated {datetime.now().strftime('%d %b %Y %H:%M')} by `council evals` "
             "from the run folders listed below. Every number is read from the run's own files.", ""]
    lines += ["## Acceptance by sample", "", "| Criterion | " + " | ".join(s.upper() for s in by_sample) + " |",
              "|---|" + "---|" * len(by_sample)]
    for c in crit:
        cells = []
        for s, runs in by_sample.items():
            oks = [r.get(c, {}).get("ok") for r in runs]
            cells.append(f"{'✅' if all(oks) else '❌'} {sum(bool(o) for o in oks)}/{len(oks)}")
        lines.append(f"| {names[c]} | " + " | ".join(cells) + " |")
    stab = {s: stability(runs) for s, runs in by_sample.items()}
    lines.append("| Stable outcome on binding and clear subjects | " + " | ".join(
        "—" if st["ok"] is None else ("✅" if st["ok"] else "❌") for st in stab.values()) + " |")
    lines += ["", f"Production gate over the whole catalog: {'✅' if gate['ok'] else '❌'} {gate['candidates']} candidates, "
              + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(gate["counts"].items()))
              + (f"; not final: {', '.join(gate['not_final'])}" if gate["not_final"] else "")
              + (f"; without evidence links: {', '.join(gate['no_evidence_links'])}" if gate["no_evidence_links"] else "")
              + (f"; wrongly eligible: {', '.join(gate['wrongly_eligible'])}" if gate["wrongly_eligible"] else "") + ".", ""]

    for s, runs in by_sample.items():
        summary["samples"][s] = {"runs": runs, "stability": stab[s]}
        lines += [f"## {s.upper()} · {SAMPLES[s][0].name}", "",
                  "| Run | Quotes | Time | Cost | Calls (failed) | Stage agreement | Problems |", "|---|---|---|---|---|---|---|"]
        for r in runs:
            probs = [f"{names[c]}: {json.dumps({k: v for k, v in r[c].items() if k != 'ok' and v}, ensure_ascii=False)}"
                     for c in crit if c in r and not r[c].get("ok")]
            sa = _json(next(d for d in run_dirs if d.name == r["run"]), "strategy_decision.json", {}).get("stage_agreement")
            tc = r.get("time_and_cost", {})
            lines.append(f"| {r['run']} | {r['quote_match']['pct']}% | {tc.get('seconds', '—')} s | ${tc.get('cost_usd', '—')} | "
                         f"{tc.get('calls', '—')} ({tc.get('failed_calls', '—')}) | {sa if sa is not None else '—'}% | "
                         f"{'<br>'.join(p.replace('|', '/') for p in probs) or 'none'} |")
        subjects = sorted(set().union(*(r.get("outcomes", {}).keys() for r in runs)))
        lines += ["", "Outcome per subject and run (agreement %):", "", "| Subject | " + " | ".join(f"run {i + 1}" for i in range(len(runs))) + " |",
                  "|---|" + "---|" * len(runs)]
        for sub in subjects:
            row = [r.get("outcomes", {}).get(sub) for r in runs]
            lines.append(f"| {sub} | " + " | ".join(
                (f"{x['outcome'].replace('_', ' ')}" + (f" {x['agreement']:.0f}" if x["agreement"] is not None else "")) if x else "—"
                for x in row) + " |")
        st = stab[s]
        lines += ["", "Stability: " + ("not measured (one run)" if st["ok"] is None else
                                      "stable" if st["ok"] else "UNSTABLE: " + "; ".join(st["unstable"])), ""]
    return "\n".join(lines), summary


def run_golden(n: int, samples: list[str]) -> list[Path]:
    """Run each sample n times, one after another (free-tier rate limits), auto-approved into the evals database."""
    from app.cli import _stage0
    os.environ["COUNCIL_DB"] = str(data_dir() / "evals" / "council_evals.db")
    out = []
    for s in samples:
        for i in range(n):
            print(f"\n=== golden run {s.upper()} {i + 1}/{n} ===")
            out.append(_stage0(str(SAMPLES[s][0]), None, review="approve"))
    return out


def write(text: str, summary: dict) -> Path:
    p = REPO_ROOT / "evals" / "report.md"
    p.write_text(text, encoding="utf-8")
    (REPO_ROOT / "evals" / "report.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return p
