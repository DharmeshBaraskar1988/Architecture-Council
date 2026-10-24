"""R3 · Fact check. A verdict and an evidence weight for every citation on every card.

Code decides everything it can: an assumed or unmatched fact is `unverified`; a source whose page has
not been fetched, or whose stored copy is older than `max_age_days` (config/sources.yaml), is
`unverified`; a decision precedent is judged by code from its outcome and weighted by its context
match, and a sample precedent never counts. The model (Vera) answers only one question, for confirmed
facts and fetched pages: does this evidence support this claim? For a page it sees the passage that
best matches the claim. Weights come from config/evidence_weights.yaml through the consensus engine,
never from the model.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

from app.agents.runtime import AgentError, AgentRuntime
from app.consensus.engine import Evidence, evidence_weight
from app.knowledge.crawler import best_passage, load_page
from app.schemas import ArgumentCard, CitationCheck, CitationKind, FactSheet, FactStatus, Stance, Verdict

PROMPT = Path(__file__).resolve().parents[1] / "agents" / "prompts" / "factcheck_judge.md"
JUDGE_TO_VERDICT = {"supports": Verdict.verified, "partly_supports": Verdict.partly_supports,
                    "contradicts": Verdict.contradicted, "not_relevant": Verdict.unverified}


class JudgeItem(BaseModel):
    id: str
    verdict: Literal["supports", "partly_supports", "contradicts", "not_relevant"]
    note: Optional[str] = None


def _check(card: ArgumentCard, ref: str, kind: CitationKind, source: str, verdict: Verdict,
           by: str, note: Optional[str], relevance: float = 1.0) -> CitationCheck:
    side = "against" if card.stance == Stance.reject else "for"
    weight = evidence_weight(Evidence(side, source, verdict, relevance=relevance))
    return CitationCheck(card=card.id, ref=ref, kind=kind, side=side, source=source, verdict=verdict,
                         weight=weight, by=by, note=note)


def judge(runtime: AgentRuntime, items: list[dict], batch_size: int = 50,
          workers: int = 2) -> tuple[dict[str, JudgeItem], list[str]]:
    """Ask the judge in parallel batches. Returns verdicts by item id and errors of failed batches."""
    system = PROMPT.read_text(encoding="utf-8")
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]

    def one(batch: list[dict]):
        try:
            return runtime.ask("fact_checker", system, json.dumps(batch, ensure_ascii=False, indent=1), list[JudgeItem]), None
        except AgentError as e:
            return [], str(e)[:300]

    out: dict[str, JudgeItem] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for answers, err in pool.map(one, batches):
            out.update({a.id: a for a in answers})
            if err:
                errors.append(err)
    return out, errors


SUPPORTS = {Stance.adopt: ("selected", "selected_with_condition"),
            Stance.adopt_with_condition: ("selected", "selected_with_condition"), Stance.reject: ("rejected",)}


def precedent_check(card: ArgumentCard, ref: str, p: dict) -> CitationCheck:
    """Code decides: a signed precedent on the same subject that went the card's way supports it,
    weighted by how closely the two projects' facts match."""
    def no(why: str) -> CitationCheck:
        return _check(card, ref, CitationKind.precedent, "decision_precedent", Verdict.unverified, "code", why)
    if p.get("is_sample"):
        return no("Sample precedent: shown for illustration, never weighted")
    if p.get("subject") != card.subject:
        return no(f"Precedent is about {p.get('subject')}, not {card.subject}")
    if p.get("reviewer_decision") == "override":
        return no("The reviewer overrode the panel on that decision")
    if p.get("outcome") not in SUPPORTS[card.stance]:
        return no(f"Precedent outcome was {p.get('outcome')}: it does not support {card.stance.value}")
    return _check(card, ref, CitationKind.precedent, "decision_precedent", Verdict.verified, "code",
                  f"{p.get('project')}: {p.get('outcome')}, context match {round(p.get('context', 0) * 100)}%",
                  relevance=p.get("context", 0.0))


def fact_check(cards: list[ArgumentCard], sheet: FactSheet, sources: dict[str, dict],
               runtime: AgentRuntime) -> tuple[list[ArgumentCard], list[CitationCheck], list[str]]:
    """Returns (cards with weight and removed set, one check per citation, judge errors)."""
    facts = {f.id: f for f in sheet.facts}
    checks: list[Optional[CitationCheck]] = []
    pending: list[tuple[int, ArgumentCard, str, CitationKind, str]] = []   # slots the judge fills
    items: list[dict] = []
    for card in cards:
        for fid in card.facts:
            f = facts[fid]                                   # R2 already removed unknown ids
            if f.status != FactStatus.confirmed:
                why = "Fact is assumed, not stated in the PRD" if f.status == FactStatus.assumed else "Fact quote not found in the PRD"
                checks.append(_check(card, fid, CitationKind.prd_fact, "prd_fact", Verdict.unverified, "code", why))
                continue
            items.append({"id": f"p{len(items) + 1}", "claim": f"{card.subject} ({card.stance.value}): {card.claim}",
                          "evidence": f"{f.key} = {json.dumps(f.value, ensure_ascii=False)}. PRD page {f.page}: \"{f.quote}\""})
            pending.append((len(checks), card, fid, CitationKind.prd_fact, "prd_fact"))
            checks.append(None)
        for c in card.citations:
            s = sources.get(c.ref, {})
            if s.get("kind") == "decision_precedent":
                checks.append(precedent_check(card, c.ref, s))
                continue
            kind = s.get("kind", "official_docs")
            page = load_page(s["url"]) if s.get("verified") else None
            if not page:
                note = ("Stored copy of the page is too old to count: fetch it again (council crawl)" if s.get("stale")
                        else "Source page not fetched (council crawl)")
                checks.append(_check(card, c.ref, c.kind, kind, Verdict.unverified, "code", note))
                continue
            items.append({"id": f"p{len(items) + 1}", "claim": f"{card.subject} ({card.stance.value}): {card.claim}",
                          "evidence": f"{s.get('title')} ({s['url']}, fetched {page.fetched_at[:10]}): "
                                      f"\"{best_passage(page.text, card.claim + ' ' + (c.quote or ''))}\""})
            pending.append((len(checks), card, c.ref, c.kind, kind))
            checks.append(None)

    answers, errors = judge(runtime, items) if items else ({}, [])
    for (slot, card, ref, kind, source), item in zip(pending, items):
        a = answers.get(item["id"])
        if a is None:
            checks[slot] = _check(card, ref, kind, source, Verdict.unverified, "code", "No verdict from the judge")
        else:
            checks[slot] = _check(card, ref, kind, source, JUDGE_TO_VERDICT[a.verdict], "judge", a.note)

    done: list[CitationCheck] = [c for c in checks if c is not None]
    out = []
    for card in cards:
        mine = [c for c in done if c.card == card.id]
        contradicted = [c.ref for c in mine if c.verdict == Verdict.contradicted]
        issues = list(card.issues)
        if contradicted:
            issues.append(f"Contradicted by {', '.join(contradicted)}: removed from the evidence")
        if not mine:
            issues.append("Reasoning only: shown, never counted")
        out.append(card.model_copy(update={"weight": 0.0 if contradicted else round(sum(c.weight or 0 for c in mine), 2),
                                           "removed": bool(contradicted), "issues": issues}))
    return out, done, errors


def summary(checks: list[CitationCheck]) -> dict:
    return {v.value: sum(c.verdict == v for c in checks) for v in Verdict}
