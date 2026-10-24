"""R4 · Challenges. Code assigns a challenger to every card; challengers attack in parallel;
code checks each challenge, and the R3 fact check weighs it like a card.

Assignment rules (all in code, the same cards always give the same assignment):
- a proposer and its challenger never run on the same provider;
- among those, prefer a voter who took a different stance on that subject, then the least loaded;
- where every card on a subject takes the same stance, the Critic must argue the opposite (counter-case).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from app.agents.runtime import AgentRuntime
from app.config import config
from app.debate.proposals import clean_evidence
from app.schemas import ArgumentCard, Challenge, ChallengeType, Citation, FactSheet, Stance

PROMPT = Path(__file__).resolve().parents[1] / "agents" / "prompts" / "challenge.md"
COUNTER_AGENT = "critic"


class ChallengeDraft(BaseModel):
    """What a model returns; everything else is filled in by code."""
    target: str
    type: ChallengeType
    text: str
    facts: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    thinking: Optional[str] = None                    # first-person note of what was weighed


def provider(agent: str) -> str:
    """Provider of the agent's configured main model, e.g. 'openai' from 'openai/gpt-4.1'."""
    return config("personas")["agents"][agent]["model"].split("/")[0]


def assign(cards: list[ArgumentCard], agents: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Returns ({challenger: [card ids or 'counter:<subject>']}, notes)."""
    stance = {(c.agent, c.subject): c.stance for c in cards}
    load = {a: 0 for a in agents}
    out: dict[str, list[str]] = {a: [] for a in agents}
    notes: list[str] = []
    for card in cards:
        if card.removed:
            continue                                         # contradicted: already out of the evidence
        options = [a for a in agents if a != card.agent and provider(a) != provider(card.agent)]
        if not options:
            options = [a for a in agents if a != card.agent]
            notes.append(f"{card.id}: no challenger on another provider; same provider used")
        if not options:
            notes.append(f"{card.id}: no other voter to challenge it")
            continue
        disagree = [a for a in options if stance.get((a, card.subject)) not in (None, card.stance)]
        pick = min(disagree or options, key=lambda a: (load[a], agents.index(a)))
        out[pick].append(card.id)
        load[pick] += 1
    counter = COUNTER_AGENT if COUNTER_AGENT in agents else agents[0]
    for subject in dict.fromkeys(c.subject for c in cards):
        live = [c for c in cards if c.subject == subject and not c.removed]
        if len(live) >= 2 and len({c.stance for c in live}) == 1:
            out[counter].append(f"counter:{subject}")
    return out, notes


def targets_for(ids: list[str], cards: list[ArgumentCard], checks: list[dict]) -> list[dict]:
    """What one challenger sees: its target cards with their verdicts, and counter-case subjects."""
    by_id = {c.id: c for c in cards}
    out = []
    for tid in ids:
        if tid.startswith("counter:"):
            subject = tid.split(":", 1)[1]
            agreed = [c for c in cards if c.subject == subject and not c.removed]
            out.append({"id": tid, "counter_case": True, "subject": subject, "panel_stance": agreed[0].stance.value,
                        "panel_claims": [c.claim for c in agreed]})
            continue
        c = by_id[tid]
        out.append({"id": tid, "counter_case": False, "subject": c.subject, "author": c.agent, "stance": c.stance.value,
                    "claim": c.claim, "benefit": c.benefit, "cost": c.cost, "condition": c.condition,
                    "evidence_weight": c.weight,
                    "verdicts": [{"ref": k["ref"], "verdict": k["verdict"], "note": k.get("note")}
                                 for k in checks if k["card"] == tid]})
    return out


def system_prompt(agent: str) -> str:
    p = config("personas")["agents"][agent]
    return (PROMPT.read_text(encoding="utf-8").replace("{{NAME}}", p["name"]).replace("{{ROLE}}", p["role"])
            .replace("{{FOCUS}}", p.get("focus", "")))


def challenge(agent: str, runtime: AgentRuntime, brief: str, targets: list[dict]) -> list[ChallengeDraft]:
    user = f"{brief}\n\nYOUR TARGETS\n{json.dumps(targets, ensure_ascii=False, indent=1)}"
    return runtime.ask(agent, system_prompt(agent), user, list[ChallengeDraft])


def check_challenges(agent: str, drafts: list[ChallengeDraft], assigned: list[str], cards: list[ArgumentCard],
                     sheet: FactSheet, sources: dict[str, dict]) -> tuple[list[Challenge], list[dict]]:
    """Code-side checks on one challenger's output. Returns (kept, dropped with reasons)."""
    by_id = {c.id: c for c in cards}
    kept: list[Challenge] = []
    dropped: list[dict] = []
    seen: set[str] = set()
    for d in drafts:
        if d.target not in assigned:
            dropped.append({"agent": agent, "target": d.target, "reason": "Not one of this agent's targets"})
            continue
        if d.target in seen:
            dropped.append({"agent": agent, "target": d.target, "reason": "Second challenge on the same target"})
            continue
        seen.add(d.target)
        facts, citations, issues = clean_evidence(d.facts, d.citations, sheet, sources)
        if d.target.startswith("counter:"):
            subject = d.target.split(":", 1)[1]
            panel = next(c.stance for c in cards if c.subject == subject and not c.removed)
            target_agent, counter = "", True
        else:
            subject, panel, target_agent, counter = by_id[d.target].subject, by_id[d.target].stance, by_id[d.target].agent, False
        kept.append(Challenge(agent=agent, target_subject=subject, target_agent=target_agent, type=d.type, text=d.text,
                              citations=citations, facts=facts, id=f"{agent}>{d.target}", target=d.target,
                              counter_case=counter, side="for" if panel == Stance.reject else "against",
                              issues=issues, thinking=d.thinking))
    return kept, dropped


def as_cards(challenges: list[Challenge]) -> list[ArgumentCard]:
    """Challenges in card form, so the R3 fact check weighs them with the same rules and judge."""
    return [ArgumentCard(agent=ch.agent, round="R4", subject=ch.target_subject,
                         stance=Stance.adopt if ch.side == "for" else Stance.reject,
                         claim=ch.text, facts=ch.facts, citations=ch.citations, id=ch.id) for ch in challenges]


def untested(cards: list[ArgumentCard], challenges: list[Challenge]) -> list[str]:
    """Subjects with live cards but no challenge at all (the plan requires at least one each)."""
    hit = {ch.target_subject for ch in challenges if not ch.removed}
    return [s for s in dict.fromkeys(c.subject for c in cards if not c.removed) if s not in hit]


def unanswered_targets(assigned: dict[str, list[str]], challenges: list[Challenge],
                       failed: Optional[set[str]] = None) -> list[dict]:
    got = {ch.target for ch in challenges}
    failed = failed or set()
    return [{"agent": a, "target": t, "reason": "challenger failed" if a in failed else "no challenge written"}
            for a, ts in assigned.items() for t in ts if t not in got]
