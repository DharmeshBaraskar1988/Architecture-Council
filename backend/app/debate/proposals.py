"""R2 · Blind proposals. Each voter writes argument cards from the same brief, without seeing
the others; code then checks every card against the fact sheet, shortlist and source list.

A card that cites an unknown fact or source keeps its claim but loses that citation, and the
card records why. A card about a framework that is not on the shortlist is dropped.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from app.agents.runtime import AgentRuntime
from app.config import config, load_dir
from app.schemas import (ArgumentCard, Citation, CitationKind, FactSheet, FactStatus,
                         RejectedAlternative, Stance)

PROMPTS = Path(__file__).resolve().parents[1] / "agents" / "prompts"
OPEN_STATUSES = ("binding", "candidate")          # shortlist statuses the panel argues about
LEAD_SUBJECTS = ("build_approach", "delivery_path")  # extra subjects only the Strategist proposes


class CardDraft(BaseModel):
    """What a model returns; agent, round, id and issues are filled in by code."""
    subject: str
    stance: Stance
    claim: str
    facts: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    benefit: Optional[str] = None
    cost: Optional[str] = None
    condition: Optional[str] = None
    rejected_alternative: Optional[RejectedAlternative] = None
    thinking: Optional[str] = None                    # first-person note of what was weighed


def voters() -> list[str]:
    return [a for a, p in config("personas")["agents"].items() if p.get("votes")]


def source_index(frameworks: Optional[list[dict]] = None) -> dict[str, dict]:
    """Citable sources by id: src-<framework>-<n>. A source is `verified` only when the crawler has a
    fresh stored copy of its page (task 1.7); `stale` when the stored copy is too old to count."""
    from app.knowledge.crawler import is_stale, load_page
    frameworks = frameworks if frameworks is not None else load_dir("frameworks")
    out = {}
    for fw in frameworks:
        for n, s in enumerate(fw.get("sources", []), 1):
            page = load_page(s["url"])
            fresh = bool(page and page.ok and not is_stale(page))
            out[f"src-{fw['id']}-{n}"] = {**s, "framework": fw["id"], "verified": fresh,
                                          "stale": bool(page and page.ok and not fresh),
                                          "fetched_at": page.fetched_at if page and page.ok else None}
    return out


MODES = {
    "production": "PRODUCTION: only production_eligible solutions may be proposed for production. A poc_only "
                  "solution may be used in the POC only with the swap plan below.",
    "poc": "POC: poc_only solutions may be proposed for the proof of concept; name the swap plan for production.",
}


def build_brief(sheet: dict, shortlist: list[dict], gate: dict, sources: dict[str, dict],
                mode: str = "production") -> str:
    """The user message every voter receives. Identical for all of them: that is what keeps R2 blind.
    `sources` holds framework sources (src-...) and decision precedents (dec-...)."""
    from app.catalog.gate import swap_plans
    open_ids = {i["id"] for i in shortlist if i["status"] in OPEN_STATUSES}
    facts = [{k: f.get(k) for k in ("id", "key", "value", "status", "page", "quote")} for f in sheet["facts"]]
    items = [{k: i[k] for k in ("id", "name", "status", "reason")} for i in shortlist]
    srcs = [{"id": sid, "framework": s["framework"], "title": s.get("title"), "kind": s.get("kind"),
             "fetched": bool(s.get("verified"))}
            for sid, s in sources.items() if s.get("framework") in open_ids]
    precedents = [{"id": sid, "subject": s["subject"], "outcome": s["outcome"], "agreement": s.get("agreement"),
                   "context_match_pct": round(s["context"] * 100), "sample_not_evidence": s["is_sample"],
                   "conditions": s.get("conditions") or None, "project": s["project"]}
                  for sid, s in sources.items() if s.get("kind") == "decision_precedent"]
    gates = {cap: [{k: r.get(k) for k in ("name", "type", "provider", "verdict")} for r in rs] for cap, rs in gate.items()}
    reuse = [{"capability": cap, "owned": r["name"]} for cap, rs in gate.items() for r in rs if r["type"] == "owned"]
    parts = [("MODE", MODES.get(mode, MODES["production"])), ("FACT SHEET", facts), ("SHORTLIST", items),
             ("SOURCES", srcs), ("PRECEDENTS (decision database; cite as precedent)", precedents),
             ("SOLUTION GATE", gates), ("REUSE OPTIONS (already owned; cheaper and no new lock-in)", reuse),
             ("SWAP PLANS (POC-only part -> production-eligible options)", swap_plans(gate)),
             ("EXISTING STACK", config("policies/existing_stack").get("owned") or []),
             ("ORG POLICY", config("policies/org_policy"))]
    return "\n\n".join(f"{title}\n{json.dumps(body, ensure_ascii=False, indent=1)}" for title, body in parts)


def system_prompt(agent: str) -> str:
    p = config("personas")["agents"][agent]
    extra = (PROMPTS / "strategist.md").read_text(encoding="utf-8") if "strategy" in p.get("leads", []) else ""
    return ((PROMPTS / "proposals.md").read_text(encoding="utf-8")
            .replace("{{NAME}}", p["name"]).replace("{{ROLE}}", p["role"])
            .replace("{{FOCUS}}", p.get("focus", "")).replace("{{EXTRA}}", extra))


def propose(agent: str, runtime: AgentRuntime, brief: str) -> list[CardDraft]:
    return runtime.ask(agent, system_prompt(agent), brief, list[CardDraft])


def clean_evidence(fact_ids: list[str], cites: list[Citation], sheet: FactSheet,
                   sources: dict[str, dict]) -> tuple[list[str], list[Citation], list[str]]:
    """Keep only facts and sources that exist. Returns (fact ids, citations, issues). Used by R2 and R4."""
    facts = {f.id: f for f in sheet.facts}
    issues: list[str] = []
    ids = list(dict.fromkeys(fact_ids + [c.ref for c in cites if c.kind == CitationKind.prd_fact]))
    unknown = [f for f in ids if f not in facts]
    if unknown:
        issues.append(f"Unknown fact ids removed: {', '.join(unknown)}")
    ids = [f for f in ids if f in facts]
    if not ids:
        issues.append("No fact cited: carries no weight")
    elif all(facts[f].status != FactStatus.confirmed for f in ids):
        issues.append("Rests only on assumed or unverified facts")
    citations = []
    for c in cites:
        if c.kind == CitationKind.prd_fact:
            continue                                      # folded into the fact ids above
        if c.kind in (CitationKind.source, CitationKind.precedent) and c.ref in sources:
            kind = CitationKind.precedent if sources[c.ref].get("kind") == "decision_precedent" else CitationKind.source
            citations.append(c.model_copy(update={"kind": kind}))
        else:
            issues.append(f"Citation not in the retrieved set, removed: {c.kind.value} {c.ref}")
    return ids, citations, issues


def check_cards(agent: str, drafts: list[CardDraft], sheet: FactSheet, shortlist: list[dict],
                sources: dict[str, dict]) -> tuple[list[ArgumentCard], list[dict]]:
    """Code-side checks on one agent's cards. Returns (kept cards, dropped cards with reasons)."""
    status = {i["id"]: i["status"] for i in shortlist}
    by_name = {i["name"].strip().lower(): i["id"] for i in shortlist if i.get("name")}
    is_lead = "strategy" in config("personas")["agents"][agent].get("leads", [])
    kept: list[ArgumentCard] = []
    dropped: list[dict] = []
    seen: set[str] = set()
    for d in drafts:
        d = d.model_copy(update={"subject": by_name.get(d.subject.strip().lower(), d.subject)})  # name → id
        if d.subject in seen:
            dropped.append({"agent": agent, "subject": d.subject, "reason": "Second card on the same subject"})
            continue
        if d.subject in LEAD_SUBJECTS:
            if not is_lead:
                dropped.append({"agent": agent, "subject": d.subject, "reason": "Only the stage lead proposes this"})
                continue
        elif status.get(d.subject) not in OPEN_STATUSES:
            dropped.append({"agent": agent, "subject": d.subject,
                            "reason": f"Not open for debate (shortlist: {status.get(d.subject, 'unknown')})"})
            continue
        seen.add(d.subject)
        fact_ids, citations, issues = clean_evidence(d.facts, d.citations, sheet, sources)
        if status.get(d.subject) == "binding" and d.stance == Stance.reject:
            issues.append("Binding framework cannot be rejected")
        if d.stance == Stance.adopt_with_condition and not (d.condition or "").strip():
            issues.append("Condition missing for adopt_with_condition")

        kept.append(ArgumentCard(agent=agent, round="R2", subject=d.subject, stance=d.stance, claim=d.claim,
                                 facts=fact_ids, citations=citations, benefit=d.benefit, cost=d.cost,
                                 condition=d.condition, rejected_alternative=d.rejected_alternative,
                                 id=f"{agent}:{d.subject}", issues=issues, thinking=d.thinking))
    return kept, dropped


def coverage(cards: list[dict], shortlist: list[dict], agents: list[str]) -> list[dict]:
    """Open subjects an agent wrote no card for (the debate engine treats these as no position)."""
    have = {(c["agent"], c["subject"]) for c in cards}
    return [{"agent": a, "subject": i["id"]} for a in agents for i in shortlist
            if i["status"] in OPEN_STATUSES and (a, i["id"]) not in have]
