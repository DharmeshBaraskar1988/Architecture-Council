"""Command line for Phase 1.

  council validate                       check every catalog file
  council gate                           production gate report for the solution catalog
  council facts --prd FILE               build a fact sheet (needs API keys)
  council crawl [--refresh | --manual URL FILE]
                                         fetch every catalog source page (allowlist) into data/sources/
  council verify [--refresh]             live gate verifier: pages, GitHub, Hugging Face, OpenSSF
  council run --prd FILE [--review ask|approve|skip] [--mode production|poc]
                                         Stage 0 through the LangGraph orchestrator, R0 to R7, then
                                         the reviewer gate; a signed run is saved as precedents
  council ledger seed|list|search|record [--run ID]
                                         the decision database (data/council.db)
  council view [ID]                      open a run in the replay viewer
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app.config import DATA_DIR


def _print_table(rows: list[list[str]], head: list[str]) -> None:
    widths = [max(len(str(x)) for x in col) for col in zip(head, *rows)] if rows else [len(h) for h in head]
    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    print(fmt.format(*head))
    print(fmt.format(*["-" * w for w in widths]))
    for r in rows:
        print(fmt.format(*[str(x) for x in r]))


def _run_dir(out: str | None) -> Path:
    rid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    d = Path(out) if out else DATA_DIR / "runs" / rid
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_validate(_a) -> int:
    from app.catalog.models import validate_catalogs
    errs = validate_catalogs()
    if errs:
        print("Catalog problems:")
        for e in errs:
            print("  -", e)
        return 1
    print("All framework and solution catalog files are valid.")
    return 0


def cmd_gate(a) -> int:
    from app.catalog.gate import gate_catalog
    res = gate_catalog()
    rows = [[cap, r.name, r.type, r.verdict.value, "; ".join(r.reasons)[:90]] for cap, rs in res.items() for r in rs]
    _print_table(rows, ["capability", "candidate", "type", "verdict", "reasons"])
    if a.out:
        Path(a.out).write_text(json.dumps({k: [asdict(r) for r in v] for k, v in res.items()}, indent=2, default=str), encoding="utf-8")
        print(f"\nWrote {a.out}")
    return 0


def cmd_crawl(a) -> int:
    from app.knowledge import crawler
    if a.manual:
        url, file = a.manual
        p = crawler.capture_file(url, Path(file))
        print(f"Stored a manual capture of {url}: {len(p.text)} characters, “{p.title[:80]}”")
        return 0
    used_by = crawler.catalog_urls()
    print(f"Fetching {len(used_by)} catalog pages (allowlist, robots.txt, {crawler.config('sources')['rate_limit_per_domain_per_minute']}"
          f" per domain per minute; stored pages younger than {crawler.config('sources')['max_age_days']} days are kept)...")
    pages = crawler.crawl(used_by, refresh=a.refresh)
    rep = crawler.report(pages, used_by)
    _print_table([[("ok" if p["ok"] else "FAILED"), p["status"] or "", p["chars"], p["url"][:90], (p["error"] or p["title"])[:60]]
                  for p in rep["pages"]], ["", "http", "chars", "url", "title / error"])
    path = crawler.write_report(rep)
    print(f"\n{rep['fetched']} stored, {rep['failed']} failed. Report: {path}")
    return 1 if rep["failed"] else 0


def cmd_verify(a) -> int:
    from app.catalog import verify
    from app.catalog.gate import gate_catalog
    print("Fetching every candidate's pages and reading GitHub, Hugging Face and OpenSSF signals...")
    doc = verify.verify_catalog(refresh=a.refresh)
    res = gate_catalog()
    rows = [[cap, r.name[:38], r.type, r.verdict.value, "; ".join(r.reasons)[:100]] for cap, rs in res.items() for r in rs]
    _print_table(rows, ["capability", "candidate", "type", "verdict", "reasons"])
    n = sum(v["verified"] for v in doc["candidates"].values())
    print(f"\n{n} of {len(doc['candidates'])} candidates verified. Results: {verify.path()}")
    return 0


def _find_run(run: str | None) -> Path:
    runs = DATA_DIR / "runs"
    if not run:
        dirs = sorted((d for d in runs.iterdir() if (d / "debate_log.jsonl").exists()), key=lambda d: d.name)
        if not dirs:
            raise SystemExit("No runs yet.")
        return dirs[-1]
    p = Path(run)
    return p if p.is_dir() else runs / run


def cmd_ledger(a) -> int:
    from app.ledger import store
    if a.action == "seed":
        print(f"Loaded {store.seed_samples()} SAMPLE precedents into {store.db_path()} (marked as samples, never weighted).")
    elif a.action == "record":
        d = _find_run(a.run)
        ids = store.record_run(d)
        print(f"Saved {len(ids)} decisions from {d.name}." if ids else f"{d.name} is not signed yet: nothing saved.")
    elif a.action == "list":
        _print_table([[r["id"], "SAMPLE" if r["is_sample"] else r["reviewer_decision"], r["subject"], r["outcome"],
                       r["agreement"] if r["agreement"] is not None else "", r["project"][:50]] for r in store.all_decisions()],
                     ["id", "signed", "subject", "outcome", "A %", "project"])
    else:
        d = _find_run(a.run)
        facts = json.loads((d / "fact_sheet.json").read_text(encoding="utf-8"))["facts"]
        _print_table([[r["id"], f"{r['context_match']}%", "SAMPLE" if r["is_sample"] else "", r["subject"], r["outcome"],
                       r["project"][:50]] for r in store.search(facts, limit=20, exclude_session=d.name, min_match=0.2)],
                     ["id", "context", "", "subject", "outcome", "project"])
    return 0


def cmd_evals(a) -> int:
    from app import evals
    os.environ.setdefault("COUNCIL_DB", str(DATA_DIR / "evals" / "council_evals.db"))
    if a.from_runs:
        dirs = [_find_run(r) for r in a.from_runs]
    else:
        dirs = evals.run_golden(a.runs, a.samples.split(","))
    text, summary = evals.report(dirs)
    path = evals.write(text, summary)
    print(f"\n{text}\n\nWrote {path}")
    return 0


def cmd_view(a) -> int:
    import webbrowser
    d = _find_run(a.run)
    url = f"{a.url.rstrip('/')}/runs/{d.name}"
    print(f"Opening {url}  (start the viewer first: npm run dev in frontend/)")
    webbrowser.open(url)
    return 0


def _ask_reviewer(summary: dict) -> dict:
    print("\nReviewer gate")
    print(f"  Binding: {', '.join(summary['binding']) or 'none'}")
    print(f"  Candidates: {', '.join(summary['candidates']) or 'none'}")
    print(f"  Cards (R2): {', '.join(f'{a} {n}' for a, n in summary['cards'].items())}")
    if summary["r2_failures"]:
        print(f"  No reply from: {', '.join(summary['r2_failures'])}")
    print(f"  Citations (R3): {', '.join(f'{k} {n}' for k, n in summary['verdicts'].items())}")
    if summary["removed_cards"]:
        print(f"  Removed (contradicted): {', '.join(summary['removed_cards'])}")
    print(f"  Challenges (R4): {', '.join(f'{k} {n}' for k, n in summary['challenges'].items())}")
    if summary["counter_cases"]:
        print(f"  Counter-cases to unanimous positions: {', '.join(summary['counter_cases'])}")
    if summary["untested"]:
        print(f"  Not challenged: {', '.join(summary['untested'])}")
    print(f"  Rebuttals (R5): rebut {summary['rebuttals']['rebut']}, concede {summary['rebuttals']['concede']}, revise {summary['rebuttals'].get('revise', 0)}; "
          f"challenges still open: {summary['challenges_open']}")
    if summary["conceded_cards"]:
        print(f"  Conceded cards: {', '.join(summary['conceded_cards'])}")
    if summary["tally"]:
        print("  Votes (R6, adopt·cond·reject): " + ", ".join(
            f"{s} {t['adopt']}·{t['adopt_with_condition']}·{t['reject']}" for s, t in summary["tally"].items()))
    if summary["r6_failures"]:
        print(f"  No vote from: {', '.join(summary['r6_failures'])}")
    if summary["pending_rounds"]:
        print(f"  Not built yet: {', '.join(summary['pending_rounds'])}")
    if summary["outcomes"]:
        print("  Outcomes (R7): " + ", ".join(f"{s} {o}{f' {a:.0f}%' if a is not None else ''}"
                                              for s, (o, a) in summary["outcomes"].items()))
        print(f"  Stage agreement: {summary['stage_agreement']}%")
    ans = input("  Approve this stage? [y = approve / anything else = override reason]: ").strip()
    if ans.lower() in ("y", "yes", ""):
        return {"decision": "approve"}
    return {"decision": "override", "reason": ans}


def _write_team(d: Path) -> None:
    """team.json: who sits at the table and which models they are set to use (main first, then fallbacks)."""
    from app.config import config
    team = {}
    for agent, p in config("personas")["agents"].items():
        fb = p.get("fallback_model") or []
        team[agent] = {"name": p["name"], "role": p["role"], "votes": bool(p.get("votes")),
                       "specialty": p.get("specialty", ""), "works_on": p.get("works_on", ""),
                       "models": [p["model"]] + (fb if isinstance(fb, list) else [fb])}
    (d / "team.json").write_text(json.dumps(team, indent=2), encoding="utf-8")


_USAGE_LOCK = __import__("threading").Lock()


def _write_usage(d: Path, rt) -> None:
    """usage.json after every model call starts or ends, so the room can show who is on which model, live."""
    with _USAGE_LOCK:
        with rt._lock:
            calls = [asdict(c) for c in rt.usage.calls]
            active = [asdict(c) for c in rt.active.values()]
        tmp = d / "usage.json.tmp"
        tmp.write_text(json.dumps({**rt.usage.summary(), "per_call": calls, "active": active}, indent=2), encoding="utf-8")
        tmp.replace(d / "usage.json")


def _stage0(prd: str, out: str | None, review: str = "ask", mode: str = "production") -> Path:
    """Run Stage 0 through the LangGraph orchestrator (app/orchestrator/graph.py)."""
    from app.agents.runtime import AgentRuntime
    from app.events.bus import EventBus
    from app.orchestrator import graph as g

    d = _run_dir(out)
    bus = EventBus(session=d.name, log_path=d / "debate_log.jsonl")
    _write_team(d)
    rt = AgentRuntime(on_change=lambda r: _write_usage(d, r))
    graph = g.build_stage0_graph(rt, bus)
    paused = g.start(graph, d.name, prd, str(d), mode)
    state = paused["state"]

    print(f"\nFact sheet · {Path(prd).name}")
    _print_table([[f["id"], f["key"], json.dumps(f["value"], ensure_ascii=False), f["status"], f.get("page") or "", (f.get("note") or "")[:50]]
                  for f in state["fact_sheet"]["facts"]], ["id", "key", "value", "status", "page", "note"])
    print("\nShortlist (R1)")
    _print_table([[i["id"], i["status"], ("assumption" if i["depends_on_assumption"] else ""), i["reason"][:60]] for i in state["shortlist"]],
                 ["framework", "status", "", "reason"])
    print("\nProposals (R2, blind)")
    _print_table([[c["agent"], c["subject"], c["stance"], ",".join(c["facts"]), len(c["citations"]), "; ".join(c["issues"])[:70]]
                  for c in state.get("cards", [])], ["agent", "subject", "stance", "facts", "sources", "issues"])
    for dc in state.get("dropped_cards", []):
        print(f"  dropped: {dc['agent']} · {dc['subject']} · {dc['reason']}")
    for f in state.get("r2_failures", []):
        print(f"  NO REPLY: {f['agent']} · {f['error'][:150]}")
    print("\nFact check (R3)   ✓ verified  ½ partly supports  ? unverified  ✗ contradicted")
    mark = {"verified": "✓", "partly_supports": "½", "unverified": "?", "contradicted": "✗"}
    checks = state.get("checks", [])
    _print_table([[c["id"], c["weight"], " ".join(f"{k['ref']}{mark[k['verdict']]}" for k in checks if k["card"] == c["id"])[:80],
                   "REMOVED" if c.get("removed") else ""] for c in state.get("cards", [])],
                 ["card", "weight", "citations", ""])
    for e in state.get("r3_errors", []):
        print(f"  JUDGE ERROR: {e[:150]}")
    print("\nChallenges (R4)")
    _print_table([[c["agent"], c["target"], c["type"], c["weight"], ("REMOVED " if c["removed"] else "") + c["text"][:70]]
                  for c in state.get("challenges", [])], ["by", "target", "type", "weight", "challenge"])
    if state.get("untested"):
        print(f"  Not challenged at all: {', '.join(state['untested'])}")
    for f in state.get("r4_failures", []):
        print(f"  NO REPLY: {f['agent']} · {f['error'][:150]}")
    print("\nRebuttals (R5)")
    answered = {c["id"]: c.get("answered") for c in state.get("challenges", [])}
    _print_table([[r["agent"], r["challenge"], r["response"], r["weight"] if r["weight"] is not None else "",
                   "card withdrawn" if r["response"] == "concede" else "proposal revised" if r["response"] == "revise"
                   else "answered" if answered.get(r["challenge"]) else "OPEN",
                   r["text"][:60]]
                  for r in state.get("rebuttals", [])], ["by", "challenge", "response", "weight", "", "text"])
    for f in state.get("r5_failures", []):
        print(f"  NO REPLY: {f['agent']} · {f['error'][:150]}")
    print("\nVote (R6, blind)   stance/confidence per voter")
    short = {"adopt": "adopt", "adopt_with_condition": "cond", "reject": "reject"}
    vs = state.get("votes", [])
    voters = list(dict.fromkeys(v["agent"] for v in vs))
    _print_table([[s] + [next((f"{short[v['stance']]}/{v['confidence']}" for v in vs if v["agent"] == a and v["subject"] == s), "-")
                         for a in voters] + [f"{t['adopt']}·{t['adopt_with_condition']}·{t['reject']}"]
                  for s, t in state.get("tally", {}).items()], ["subject"] + voters + ["adopt·cond·reject"])
    for f in state.get("r6_failures", []):
        print(f"  NO REPLY: {f['agent']} · {f['error'][:150]}")
    dec = state.get("decision")
    if dec:
        rv = dec["revote"]
        if rv["subjects"]:
            print(f"\nRe-vote (R7) on {', '.join(rv['subjects'])}")
            for s, c in rv["compromises"].items():
                print(f"  compromise · {s}: {c}")
        print("\nDecision board (R7)   V vote %, E evidence %, A agreement %")
        _print_table([[r["subject"], r["vote_support"] if r["vote_support"] is not None else "",
                       r["evidence_balance"] if r["evidence_balance"] is not None else "",
                       r["agreement"] if r["agreement"] is not None else "", r["outcome"] + (" (re-voted)" if r["revoted"] else ""),
                       (r["guardrail"] or (r["reasons"][-1] if r["reasons"] else ""))[:70]]
                      for r in dec["board"]], ["subject", "V", "E", "A", "outcome", "guardrail / reason"])
        flags = [f"{r['subject']}: {f}" for r in dec["board"] for f in r["flags"]]
        for f in flags:
            print(f"  flag · {f}")
        print(f"\nStage agreement: {dec['stage_agreement']}%")
        print(f"Position statement ({dec['statement_by']}):\n  {dec['statement']}")

    summary = paused["for_reviewer"]
    if review == "ask":
        answer = _ask_reviewer(summary)
    elif review == "approve":
        answer = {"decision": "approve", "auto": True, "reason": "auto-approved (--review approve)"}
        print("\nReviewer gate: auto-approved (--review approve)")
    else:
        print("\nReviewer gate: left paused (--review skip); nothing signed")
        answer = None
    if answer:
        final = g.resume(graph, d.name, answer)
        print(f"  Recorded: {final['review']['decision']}; {len(final.get('recorded', []))} decisions saved to the decision database")

    _write_usage(d, rt)
    print(f"\nUsage: {rt.usage.summary()}")
    print(f"Run saved to {d}")
    if summary["pending_rounds"]:
        print("Not yet built: " + ", ".join(summary["pending_rounds"]) + ".")
    return d


def cmd_facts(a) -> int:
    _stage0(a.prd, a.out, a.review, a.mode)
    return 0


def cmd_run(a) -> int:
    _stage0(a.prd, a.out, a.review, a.mode)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows terminals and the ₹ sign
    except Exception:
        pass
    _load_dotenv()
    p = argparse.ArgumentParser(prog="council", description="AI Architecture Council · Phase 1")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate").set_defaults(fn=cmd_validate)
    g = sub.add_parser("gate"); g.add_argument("--out"); g.set_defaults(fn=cmd_gate)
    c = sub.add_parser("crawl", help="fetch every catalog source page into data/sources/")
    c.add_argument("--refresh", action="store_true", help="fetch again even if a fresh copy is stored")
    c.add_argument("--manual", nargs=2, metavar=("URL", "FILE"),
                   help="store a page you saved from your browser, for sites that block automated fetching")
    c.set_defaults(fn=cmd_crawl)
    v = sub.add_parser("verify", help="live gate verifier: fetch every candidate's evidence")
    v.add_argument("--refresh", action="store_true", help="fetch pages again even if fresh copies are stored")
    v.set_defaults(fn=cmd_verify)
    for name, fn in (("facts", cmd_facts), ("run", cmd_run)):
        s = sub.add_parser(name); s.add_argument("--prd", required=True); s.add_argument("--out")
        s.add_argument("--review", choices=["ask", "approve", "skip"], default="ask", help="how the reviewer gate is answered")
        s.add_argument("--mode", choices=["production", "poc"], default="production",
                       help="production: only production-eligible solutions for production (default)")
        s.set_defaults(fn=fn)
    lg = sub.add_parser("ledger", help="decision database: seed, list, search, record")
    lg.add_argument("action", choices=["seed", "list", "search", "record"])
    lg.add_argument("--run", help="run folder or id (search: precedents for its facts; record: save its signed decisions)")
    lg.set_defaults(fn=cmd_ledger)
    ev = sub.add_parser("evals", help="golden runs on S1-S3 and the acceptance report (evals/report.md)")
    ev.add_argument("--runs", type=int, default=3, help="runs per sample (live, needs keys)")
    ev.add_argument("--samples", default="s1,s2,s3")
    ev.add_argument("--from", dest="from_runs", nargs="+", metavar="ID", help="report on existing runs instead")
    ev.set_defaults(fn=cmd_evals)
    vw = sub.add_parser("view", help="open a run in the replay viewer (frontend must be running)")
    vw.add_argument("run", nargs="?", help="run id (default: the latest)")
    vw.add_argument("--url", default="http://localhost:3000")
    vw.set_defaults(fn=cmd_view)
    a = p.parse_args(argv)
    return a.fn(a)


def _load_dotenv() -> None:
    """Minimal .env loader (repo root), so no extra dependency is needed."""
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip() and k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()


if __name__ == "__main__":
    raise SystemExit(main())
