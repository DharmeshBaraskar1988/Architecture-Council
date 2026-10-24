"""Decision database (task 1.8): every signed decision becomes a precedent for later sessions.

SQLite in data/council.db for Phase 1 (no Docker needed); the `decisions` table has the same columns
as infra/db/init.sql, so moving to PostgreSQL later is a change of connection, not of data.

A precedent's relevance to a new session is its *context match*: the share of the decision-relevant
facts (cloud, compliance, data, scale, workload shape) on which the two documents agree. Code
computes it; no model is involved. Sample precedents are marked `is_sample` and never carry weight.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import REPO_ROOT, data_dir, load_yaml

SAMPLES = REPO_ROOT / "data" / "precedents" / "samples.yaml"

# Facts that shape an architecture decision. Numbers are compared in bands, not exactly.
CONTEXT_KEYS = ("cloud_provider", "card_payments", "personal_data", "users_in_eu", "users_in_india", "health_data",
                "financial_documents", "public_web_app", "ai_generated_content", "audio_or_video_output",
                "independent_scaling_need", "async_workflows", "containerised", "team_size", "expected_daily_users")
BANDS = {"team_size": (5, 15, 50), "expected_daily_users": (1_000, 10_000, 100_000, 1_000_000)}

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY, session_id TEXT, project TEXT, stage TEXT, subject TEXT, subject_name TEXT,
  outcome TEXT, agreement REAL, vote_support REAL, evidence_balance REAL,
  rationale TEXT, dissent TEXT, conditions TEXT, evidence TEXT, context TEXT,
  reviewer TEXT, reviewer_decision TEXT, reviewer_override_reason TEXT,
  is_sample INTEGER NOT NULL DEFAULT 0, decided_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS decisions_subject ON decisions(subject);
"""
COLUMNS = ("id", "session_id", "project", "stage", "subject", "subject_name", "outcome", "agreement", "vote_support",
           "evidence_balance", "rationale", "dissent", "conditions", "evidence", "context", "reviewer",
           "reviewer_decision", "reviewer_override_reason", "is_sample", "decided_at")


def db_path() -> Path:
    """data/council.db, or COUNCIL_DB (evals use their own file so golden runs never become precedents)."""
    import os
    return Path(os.environ["COUNCIL_DB"]) if os.environ.get("COUNCIL_DB") else data_dir() / "council.db"


def connect() -> sqlite3.Connection:
    db_path().parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _band(key: str, value: Any) -> Any:
    if key not in BANDS:
        return value
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return sum(n > b for b in BANDS[key])


def context(facts: list[dict]) -> dict[str, Any]:
    """The decision-relevant profile of a document: confirmed facts only, numbers in bands."""
    return {f["key"]: _band(f["key"], f["value"]) for f in facts
            if f["key"] in CONTEXT_KEYS and f.get("status", "confirmed") == "confirmed" and f.get("value") is not None}


def context_match(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Share of facts known in either profile on which both agree (0..1). A fact known in only one
    profile counts as a difference, so two thin profiles never look alike by accident."""
    keys = set(a) | set(b)
    if not keys:
        return 0.0
    return sum(k in a and k in b and a[k] == b[k] for k in keys) / len(keys)


def _insert(con: sqlite3.Connection, row: dict) -> None:
    con.execute(f"INSERT OR REPLACE INTO decisions ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                [row.get(c) for c in COLUMNS])


def record_run(run_dir: Path) -> list[str]:
    """Write every subject of a signed run to the database. Returns the decision ids.
    Does nothing for a run nobody has signed. Safe to run twice (same ids are replaced)."""
    run_dir = Path(run_dir)
    review_p, decision_p = run_dir / "review.json", run_dir / "strategy_decision.json"
    if not review_p.exists() or not decision_p.exists():
        return []
    review = json.loads(review_p.read_text(encoding="utf-8"))
    decision = json.loads(decision_p.read_text(encoding="utf-8"))
    sheet = json.loads((run_dir / "fact_sheet.json").read_text(encoding="utf-8"))
    chs = json.loads((run_dir / "challenges.json").read_text(encoding="utf-8"))["challenges"] \
        if (run_dir / "challenges.json").exists() else []
    ctx = json.dumps(context(sheet["facts"]))
    when = datetime.fromtimestamp(review_p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    ids = []
    with closing(connect()) as con, con:
        for r in decision["board"]:
            dissent = [c["text"] for c in chs if c.get("target_subject") == r["subject"]
                       and not c.get("answered") and not c.get("removed")][:3]
            row = {"id": f"dec-{run_dir.name}-{r['subject']}", "session_id": run_dir.name, "project": sheet["document"],
                   "stage": decision.get("stage", "strategy"), "subject": r["subject"], "subject_name": r.get("name"),
                   "outcome": r["outcome"], "agreement": r.get("agreement"), "vote_support": r.get("vote_support"),
                   "evidence_balance": r.get("evidence_balance"), "rationale": "; ".join(r.get("reasons", [])),
                   "dissent": json.dumps(dissent, ensure_ascii=False), "conditions": r.get("guardrail") or "",
                   "evidence": json.dumps({"flags": r.get("flags", []), "open_objections": r.get("open_objections", [])},
                                          ensure_ascii=False),
                   "context": ctx, "reviewer": review.get("reviewer", "reviewer"), "reviewer_decision": review.get("decision"),
                   "reviewer_override_reason": review.get("reason") or "", "is_sample": 0, "decided_at": when}
            _insert(con, row)
            ids.append(row["id"])
    return ids


def seed_samples(path: Path = SAMPLES) -> int:
    """Load the clearly marked sample precedents (is_sample = 1). Returns how many."""
    items = load_yaml(path).get("decisions", []) if path.exists() else []
    with closing(connect()) as con, con:
        for d in items:
            _insert(con, {**d, "id": d["id"], "is_sample": 1, "reviewer": "sample", "reviewer_decision": "sample",
                          "context": json.dumps(d.get("context", {})), "decided_at": d.get("decided_at", "2026-01-01"),
                          "dissent": json.dumps(d.get("dissent", [])), "evidence": "{}"})
    return len(items)


def all_decisions() -> list[dict]:
    with closing(connect()) as con:
        return [dict(r) for r in con.execute("SELECT * FROM decisions ORDER BY decided_at DESC")]


def search(facts: list[dict], subject: Optional[str] = None, min_match: float = 0.4,
           limit: int = 5, exclude_session: Optional[str] = None, exclude_project: Optional[str] = None) -> list[dict]:
    """Precedents for a document, best context match first, each with its context % (0..100).
    A document never finds its own earlier runs (exclude_project): citing yourself is circular."""
    mine = context(facts)
    with closing(connect()) as con:
        q, args = "SELECT * FROM decisions", []
        if subject:
            q, args = q + " WHERE subject = ?", [subject]
        rows = [dict(r) for r in con.execute(q, args)]
    out = []
    for r in rows:
        if (exclude_session and r["session_id"] == exclude_session) or (exclude_project and r["project"] == exclude_project):
            continue
        m = context_match(mine, json.loads(r["context"] or "{}"))
        if m >= min_match:
            out.append({**r, "context_match": round(m * 100), "is_sample": bool(r["is_sample"])})
    out.sort(key=lambda r: (-r["context_match"], r["is_sample"], r["decided_at"]))
    return out[:limit] if limit else out


def precedent_index(facts: list[dict], subjects: list[str], session: Optional[str] = None,
                    per_subject: int = 2, project: Optional[str] = None) -> dict[str, dict]:
    """Citable precedents for this session by decision id, in the same shape as the source index."""
    out = {}
    for s in subjects:
        for r in search(facts, subject=s, limit=per_subject, exclude_session=session, exclude_project=project):
            out[r["id"]] = {"kind": "decision_precedent", "subject": s, "outcome": r["outcome"],
                            "project": r["project"], "agreement": r["agreement"], "context": r["context_match"] / 100,
                            "is_sample": r["is_sample"], "reviewer_decision": r["reviewer_decision"],
                            "conditions": r["conditions"], "verified": True,
                            "title": f"{'SAMPLE ' if r['is_sample'] else ''}precedent: {r['project']} chose "
                                     f"{r['outcome'].replace('_', ' ')} for {r['subject_name'] or s}"}
    return out
