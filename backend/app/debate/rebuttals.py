"""R5 · Rebuttals. Each challenged author answers: rebut with new evidence, or concede.
The stage lead's build approach and delivery path cannot be dropped, only revised: the strategy must
always name both, so a challenge to them is answered by changing the proposal.

Code decides who answers (the card's author; for a counter-case, the author of the panel's
best-evidenced card on that subject), checks each answer, and sets the two flags the vote uses:
- a challenge is `answered` only when its rebuttal carries evidence weight after the fact check;
- a card is `conceded` when its author concedes, and is withdrawn from the evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.agents.runtime import AgentRuntime
from app.config import config
from app.debate.proposals import LEAD_SUBJECTS, clean_evidence
from app.schemas import ArgumentCard, Challenge, Citation, FactSheet, Rebuttal, Stance

PROMPT = Path(__file__).resolve().parents[1] / "agents" / "prompts" / "rebuttal.md"
MARKER = "CHALLENGES TO YOUR CARDS"


class RebuttalDraft(BaseModel):
    """What a model returns; everything else is filled in by code."""
    challenge: str
    response: Literal["rebut", "concede", "revise"]
    text: str
    revised_claim: Optional[str] = None
    revised_condition: Optional[str] = None
    facts: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    thinking: Optional[str] = None                    # first-person note of what was weighed


def responder(ch: Challenge, cards: list[ArgumentCard], agents: list[str]) -> str | None:
    """Who answers a challenge: the card's author, or for a counter-case the panel's strongest card."""
    if not ch.counter_case:
        return ch.target_agent
    live = [c for c in cards if c.subject == ch.target_subject and not c.removed and c.agent in agents
            and c.agent != ch.agent]                         # nobody answers their own counter-case
    if not live:
        return None
    return max(live, key=lambda c: (c.weight or 0.0, -agents.index(c.agent))).agent


def assign(challenges: list[Challenge], cards: list[ArgumentCard], agents: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {a: [] for a in agents}
    for ch in challenges:
        if ch.removed:
            continue                                         # contradicted challenges need no answer
        who = responder(ch, cards, agents)
        if who in out:
            out[who].append(ch.id)
    return out


def items_for(ids: list[str], challenges: list[Challenge], cards: list[ArgumentCard], checks: list[dict]) -> list[dict]:
    """What one author sees: each challenge, the card it attacks, and the verdicts on both."""
    chs = {c.id: c for c in challenges}
    by_card = {c.id: c for c in cards}
    out = []
    for cid in ids:
        ch = chs[cid]
        card = by_card.get(ch.target)
        if card is None:                                     # counter-case: the panel's position
            card = max((c for c in cards if c.subject == ch.target_subject and not c.removed),
                       key=lambda c: c.weight or 0.0)
        out.append({"challenge": cid, "counter_case": ch.counter_case, "subject": ch.target_subject,
                    "your_card": {"stance": card.stance.value, "claim": card.claim, "facts": card.facts,
                                  "evidence_weight": card.weight,
                                  "verdicts": [{"ref": k["ref"], "verdict": k["verdict"]} for k in checks if k["card"] == card.id]},
                    "challenge_by": ch.agent, "type": ch.type.value, "text": ch.text, "challenge_facts": ch.facts,
                    "challenge_weight": ch.weight,
                    "challenge_verdicts": [{"ref": k["ref"], "verdict": k["verdict"]} for k in checks if k["card"] == cid]})
    return out


def system_prompt(agent: str) -> str:
    p = config("personas")["agents"][agent]
    return (PROMPT.read_text(encoding="utf-8").replace("{{NAME}}", p["name"]).replace("{{ROLE}}", p["role"])
            .replace("{{FOCUS}}", p.get("focus", "")))


def rebut(agent: str, runtime: AgentRuntime, brief: str, items: list[dict]) -> list[RebuttalDraft]:
    user = f"{brief}\n\n{MARKER}\n{json.dumps(items, ensure_ascii=False, indent=1)}"
    return runtime.ask(agent, system_prompt(agent), user, list[RebuttalDraft])


def check_rebuttals(agent: str, drafts: list[RebuttalDraft], assigned: list[str], challenges: list[Challenge],
                    sheet: FactSheet, sources: dict[str, dict]) -> tuple[list[Rebuttal], list[dict]]:
    chs = {c.id: c for c in challenges}
    kept: list[Rebuttal] = []
    dropped: list[dict] = []
    seen: set[str] = set()
    for d in drafts:
        if d.challenge not in assigned:
            dropped.append({"agent": agent, "challenge": d.challenge, "reason": "Not a challenge this agent answers"})
            continue
        if d.challenge in seen:
            dropped.append({"agent": agent, "challenge": d.challenge, "reason": "Second answer to the same challenge"})
            continue
        seen.add(d.challenge)
        ch = chs[d.challenge]
        response, revised, notes = d.response, d.revised_claim, []
        lead = ch.target_subject in LEAD_SUBJECTS and not ch.counter_case
        if lead and response == "concede":
            response, revised = "revise", d.revised_claim or d.text
            notes.append("Build approach and delivery path are revised, not withdrawn")
        elif not lead and response == "revise":
            response = "concede"
            notes.append("Only the build approach and delivery path can be revised: counted as a concession")
        if response == "revise" and not (revised or "").strip():
            revised = d.text
        facts, citations, issues = (clean_evidence(d.facts, d.citations, sheet, sources) if response != "concede"
                                    else ([], [], []))
        if response == "revise":
            issues = [i for i in issues if not i.startswith("No fact cited")]   # a revision accepts the point
        kept.append(Rebuttal(agent=agent, challenge=ch.id, target=ch.target, subject=ch.target_subject,
                             response=response, text=d.text, facts=facts, citations=citations, issues=notes + issues,
                             revised_claim=revised if response == "revise" else None,
                             revised_condition=d.revised_condition if response == "revise" else None,
                             side="against" if ch.side == "for" else "for", id=f"re:{ch.id}",
                             thinking=d.thinking))
    return kept, dropped


def as_cards(rebuttals: list[Rebuttal]) -> list[ArgumentCard]:
    """Rebuttals in card form, so the R3 fact check weighs them with the same rules and judge."""
    return [ArgumentCard(agent=r.agent, round="R5", subject=r.subject, claim=r.text, facts=r.facts,
                         citations=r.citations, id=r.id, stance=Stance.adopt if r.side == "for" else Stance.reject)
            for r in rebuttals]


def apply(cards: list[ArgumentCard], challenges: list[Challenge],
          rebuttals: list[Rebuttal]) -> tuple[list[ArgumentCard], list[Challenge]]:
    """Set `answered` on challenges and `conceded` on cards from the weighed rebuttals. A revision
    answers its challenge (the point is taken into the proposal) and replaces the card's claim."""
    answered = {r.challenge for r in rebuttals if r.response == "rebut" and not r.removed and (r.weight or 0) > 0}
    answered |= {r.challenge for r in rebuttals if r.response == "revise"}
    conceded = {r.target for r in rebuttals if r.response == "concede" and not r.target.startswith("counter:")}
    revised: dict[str, Rebuttal] = {}
    for r in rebuttals:
        if r.response == "revise":
            revised[r.target] = r                                # several revisions: the last one stands
    out = []
    for c in cards:
        c = c.model_copy(update={"conceded": c.id in conceded})
        r = revised.get(c.id)
        if r:
            c = c.model_copy(update={"claim": r.revised_claim, "condition": r.revised_condition or c.condition,
                                     "issues": c.issues + [f"Revised in R5 after {r.challenge}"]})
        out.append(c)
    return out, [c.model_copy(update={"answered": c.id in answered}) for c in challenges]


def unanswered(assigned: dict[str, list[str]], rebuttals: list[Rebuttal], failed: set[str]) -> list[dict]:
    got = {r.challenge for r in rebuttals}
    return [{"agent": a, "challenge": c, "reason": "author failed" if a in failed else "no answer written"}
            for a, ids in assigned.items() for c in ids if c not in got]
