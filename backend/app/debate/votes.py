"""R6 · Blind vote. Every voter votes on every open subject at the same time, from the same
ballot: what survived R2–R5 (live cards, withdrawn cards, challenges and whether they were
answered, rebuttals), each with its evidence weight. Nobody sees another vote.

Code checks every vote (subject on the ballot, one vote each, `convinced_by` names a real ballot
item, condition present when required) and records abstentions. The numbers come in R7.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from app.agents.runtime import AgentRuntime
from app.config import config
from app.debate.proposals import LEAD_SUBJECTS, OPEN_STATUSES
from app.schemas import ArgumentCard, Challenge, Rebuttal, Stance, Vote

PROMPT = Path(__file__).resolve().parents[1] / "agents" / "prompts" / "vote.md"
MARKER = "BALLOT"


class VoteDraft(BaseModel):
    """What a model returns; agent and issues are filled in by code."""
    subject: str
    stance: Stance
    confidence: int = Field(ge=1, le=5)
    convinced_by: str = ""
    condition: Optional[str] = None
    thinking: Optional[str] = None                    # first-person note of what was weighed


def subjects(shortlist: list[dict], cards: list[ArgumentCard]) -> list[tuple[str, str]]:
    """(subject, status) pairs on the ballot: open frameworks, then the lead subjects that have a card."""
    out = [(i["id"], i["status"]) for i in shortlist if i["status"] in OPEN_STATUSES]
    out += [(s, "lead") for s in LEAD_SUBJECTS if any(c.subject == s for c in cards)]
    return out


def ballot(shortlist: list[dict], cards: list[ArgumentCard], challenges: list[Challenge],
           rebuttals: list[Rebuttal]) -> list[dict]:
    """The same ballot for every voter (that is what keeps R6 blind)."""
    out = []
    for subject, status in subjects(shortlist, cards):
        mine = [c for c in cards if c.subject == subject]
        chs = [c for c in challenges if c.target_subject == subject and not c.removed]
        out.append({
            "subject": subject, "status": status,
            "cards": [{"id": c.id, "author": c.agent, "stance": c.stance.value, "claim": c.claim,
                       "condition": c.condition, "weight": c.weight}
                      for c in mine if not c.removed and not c.conceded],
            "withdrawn": [{"id": c.id, "why": "conceded" if c.conceded else "contradicted by a fact"}
                          for c in mine if c.removed or c.conceded],
            "challenges": [{"id": c.id, "target": c.target, "type": c.type.value, "text": c.text,
                            "weight": c.weight, "answered": c.answered} for c in chs],
            "rebuttals": [{"id": r.id, "challenge": r.challenge, "response": r.response, "text": r.text,
                           "weight": r.weight, **({"revised_claim": r.revised_claim} if r.revised_claim else {})}
                          for r in rebuttals if r.subject == subject],
        })
    return out


def ballot_ids(items: list[dict]) -> set[str]:
    ids = {x["id"] for b in items for k in ("cards", "withdrawn", "challenges", "rebuttals") for x in b[k]}
    return ids | {b["compromise"]["id"] for b in items if b.get("compromise")}     # R7 re-vote ballots


def system_prompt(agent: str) -> str:
    p = config("personas")["agents"][agent]
    return (PROMPT.read_text(encoding="utf-8").replace("{{NAME}}", p["name"]).replace("{{ROLE}}", p["role"])
            .replace("{{FOCUS}}", p.get("focus", "")))


def facts_brief(sheet: dict) -> str:
    facts = [{k: f.get(k) for k in ("id", "key", "value", "status")} for f in sheet["facts"]]
    return "FACT SHEET\n" + json.dumps(facts, ensure_ascii=False, indent=1)


def vote(agent: str, runtime: AgentRuntime, sheet: dict, items: list[dict]) -> list[VoteDraft]:
    user = f"{facts_brief(sheet)}\n\n{MARKER}\n{json.dumps(items, ensure_ascii=False, indent=1)}"
    return runtime.ask(agent, system_prompt(agent), user, list[VoteDraft])


def check_votes(agent: str, drafts: list[VoteDraft], items: list[dict]) -> tuple[list[Vote], list[dict]]:
    """Code-side checks on one voter's ballot. Returns (kept votes, dropped with reasons)."""
    on_ballot = {b["subject"] for b in items}
    ids = ballot_ids(items)
    kept: list[Vote] = []
    dropped: list[dict] = []
    seen: set[str] = set()
    for d in drafts:
        if d.subject not in on_ballot:
            dropped.append({"agent": agent, "subject": d.subject, "reason": "Not on the ballot"})
            continue
        if d.subject in seen:
            dropped.append({"agent": agent, "subject": d.subject, "reason": "Second vote on the same subject"})
            continue
        seen.add(d.subject)
        issues = []
        if d.convinced_by not in ids:
            issues.append(f"convinced_by is not a ballot item: '{d.convinced_by}'")
        if d.stance == Stance.adopt_with_condition and not (d.condition or "").strip():
            issues.append("Condition missing for adopt_with_condition")
        kept.append(Vote(agent=agent, subject=d.subject, stance=d.stance, confidence=d.confidence,
                         convinced_by=d.convinced_by, condition=d.condition, issues=issues,
                         thinking=d.thinking))
    return kept, dropped


def abstentions(votes: list[Vote], items: list[dict], agents: list[str], failed: set[str]) -> list[dict]:
    have = {(v.agent, v.subject) for v in votes}
    return [{"agent": a, "subject": b["subject"], "reason": "voter failed" if a in failed else "no vote cast"}
            for a in agents for b in items if (a, b["subject"]) not in have]


def tally(votes: list[Vote], items: list[dict]) -> dict[str, dict[str, int]]:
    """Votes per stance per subject (counts only; R7 computes V, E and A)."""
    return {b["subject"]: {s.value: sum(v.subject == b["subject"] and v.stance == s for v in votes) for s in Stance}
            for b in items}
