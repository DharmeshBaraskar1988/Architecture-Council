"""R7 · Converge. Turns the R6 votes and the weighed evidence of R3–R5 into one decision per
subject through the consensus engine (pure functions), runs one compromise re-vote for split
subjects (40–59%), and has the Moderator write the guardrails and the position statement.

Code decides every number and outcome. The Moderator only writes words around them.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from app.agents.runtime import AgentError, AgentRuntime
from app.config import config
from app.consensus.engine import Decision, Evidence, Outcome, decide, stage_agreement
from app.debate.votes import VoteDraft, facts_brief
from app.schemas import ArgumentCard, Challenge, Rebuttal, Verdict, Vote

PROMPTS = Path(__file__).resolve().parents[1] / "agents" / "prompts"
REVOTE_MARKER = "REVOTE"
COMPROMISE_MARKER = "SPLIT SUBJECTS"
BOARD_MARKER = "DECISION BOARD"


def evidence_for(subject: str, cards: list[ArgumentCard], challenges: list[Challenge],
                 rebuttals: list[Rebuttal], checks: list[dict]) -> list[Evidence]:
    """The evidence that survived, for one subject. A fact or source cited by several arguments on
    the same side counts once (its best verdict): repeating an argument does not make it stronger.
    Evidence from a challenge counts as answered only if every challenge citing it was answered."""
    live = {c.id for c in cards if c.subject == subject and not c.removed and not c.conceded}
    chs = {c.id: c for c in challenges if c.target_subject == subject and not c.removed}
    rebs = {r.id for r in rebuttals if r.subject == subject and r.response == "rebut" and not r.removed}
    best: dict[tuple[str, str], dict] = {}
    answered: dict[tuple[str, str], bool] = {}
    for k in checks:
        if k["card"] not in live and k["card"] not in chs and k["card"] not in rebs:
            continue
        key = (k["side"], k["ref"])
        weight = -1.0 if k["weight"] is None else k["weight"]               # contradicted ranks lowest
        if key not in best or weight > (-1.0 if best[key]["weight"] is None else best[key]["weight"]):
            best[key] = k
        if k["card"] in chs:
            answered[key] = answered.get(key, True) and chs[k["card"]].answered
    # Only challenges are objections that need an answer; a card's own evidence was tested in R4 instead.
    return [Evidence(side=k["side"], source=k["source"], verdict=Verdict(k["verdict"]), relevance=1.0,
                     answered=answered.get(key, True), label=f"{k['ref']} ({k['card']})")
            for key, k in best.items()]


def decide_all(items: list[dict], shortlist: list[dict], votes: list[Vote], cards: list[ArgumentCard],
               challenges: list[Challenge], rebuttals: list[Rebuttal], checks: list[dict]) -> list[Decision]:
    status = {i["id"]: i for i in shortlist}
    out = []
    for b in items:
        s = b["subject"]
        item = status.get(s, {})
        mine = [v for v in votes if v.subject == s]
        if not mine and item.get("status") != "binding":
            out.append(Decision(s, Outcome.reviewer_decides, None, None, None,
                                ["No votes cast: the reviewer decides with the arguments shown"]))
            continue
        out.append(decide(s, mine,
                          evidence_for(s, cards, challenges, rebuttals, checks),
                          binding=item.get("status") == "binding",
                          key_fact_assumed=bool(item.get("depends_on_assumption")) and item.get("status") != "binding",
                          challenged=any(c.target_subject == s and not c.removed for c in challenges)))
    return out


def needs_revote(d: Decision) -> bool:
    """Split by the numbers (40–59%), not capped by an unanswered objection: a re-vote can change it."""
    return (d.outcome == Outcome.reviewer_decides and d.agreement is not None
            and not any(r.startswith("Capped at") for r in d.reasons))


# ---------- compromise and re-vote ----------
class CompromiseDraft(BaseModel):
    subject: str
    compromise: str


def compromises(runtime: AgentRuntime, split: list[str], items: list[dict], votes: list[Vote],
                decisions: dict[str, Decision]) -> dict[str, str]:
    """The Moderator's compromise per split subject; falls back to the voters' most common condition."""
    payload = []
    for s in split:
        b = next(x for x in items if x["subject"] == s)
        payload.append({"subject": s, "agreement": decisions[s].agreement,
                        "votes": [{"agent": v.agent, "stance": v.stance.value, "confidence": v.confidence,
                                   "condition": v.condition} for v in votes if v.subject == s],
                        "open_objections": [c["text"] for c in b["challenges"] if not c["answered"]],
                        "arguments": [{"stance": c["stance"], "claim": c["claim"], "weight": c["weight"]} for c in b["cards"]]})
    try:
        drafts = runtime.ask("moderator", (PROMPTS / "compromise.md").read_text(encoding="utf-8"),
                             f"{COMPROMISE_MARKER}\n{json.dumps(payload, ensure_ascii=False, indent=1)}", list[CompromiseDraft])
        got = {d.subject: d.compromise for d in drafts if d.subject in split}
    except AgentError:
        got = {}
    for s in split:
        if s not in got:
            conds = Counter(v.condition for v in votes if v.subject == s and v.condition)
            got[s] = conds.most_common(1)[0][0] if conds else "Adopt for the pilot only and revisit at its end."
    return got


def revote_items(items: list[dict], comp: dict[str, str]) -> list[dict]:
    return [{**b, "compromise": {"id": f"compromise:{b['subject']}", "text": comp[b["subject"]]}}
            for b in items if b["subject"] in comp]


def revote_prompt(agent: str) -> str:
    p = config("personas")["agents"][agent]
    return ((PROMPTS / "revote.md").read_text(encoding="utf-8").replace("{{NAME}}", p["name"])
            .replace("{{ROLE}}", p["role"]).replace("{{FOCUS}}", p.get("focus", "")))


def revote(agent: str, runtime: AgentRuntime, sheet: dict, items: list[dict]) -> list[VoteDraft]:
    user = f"{facts_brief(sheet)}\n\n{REVOTE_MARKER}\n{json.dumps(items, ensure_ascii=False, indent=1)}"
    return runtime.ask(agent, revote_prompt(agent), user, list[VoteDraft])


def merge_votes(first: list[Vote], second: list[Vote], subjects: set[str]) -> list[Vote]:
    """Re-vote replaces a voter's first vote on a re-voted subject; a voter who did not re-vote keeps it."""
    again = {(v.agent, v.subject) for v in second}
    return [v for v in first if (v.agent, v.subject) not in again] + [v for v in second if v.subject in subjects]


# ---------- guardrails and statement ----------
class StatementDraft(BaseModel):
    statement: str
    guardrails: dict[str, str] = {}


LEAD_NAMES = {"build_approach": "Build approach", "delivery_path": "Delivery path"}


def board(decisions: list[Decision], votes: list[Vote], items: list[dict],
          guardrails: Optional[dict[str, str]] = None, revoted: Optional[set[str]] = None,
          names: Optional[dict[str, str]] = None) -> list[dict]:
    by_subject = {b["subject"]: b for b in items}
    names = {**LEAD_NAMES, **(names or {})}
    out = []
    for d in decisions:
        b = by_subject.get(d.subject, {})
        out.append({"subject": d.subject, "name": names.get(d.subject, d.subject),
                    "outcome": d.outcome.value, "agreement": d.agreement,
                    "vote_support": d.vote_support, "evidence_balance": d.evidence_balance,
                    "reasons": d.reasons, "flags": d.flags, "revoted": d.subject in (revoted or set()),
                    "votes": [{"agent": v.agent, "stance": v.stance.value, "confidence": v.confidence,
                               "convinced_by": v.convinced_by, "condition": v.condition}
                              for v in votes if v.subject == d.subject],
                    "open_objections": [c["text"] for c in b.get("challenges", []) if not c["answered"]],
                    "guardrail": (guardrails or {}).get(d.subject)})
    return out


def fallback_statement(rows: list[dict]) -> str:
    by = {o: [r["subject"] for r in rows if r["outcome"] == o] for o in {r["outcome"] for r in rows}}
    parts = [f"{label}: {', '.join(by[o])}." for o, label in
             (("selected", "Selected"), ("selected_with_condition", "Selected with conditions"),
              ("reviewer_decides", "Left to the reviewer"), ("parked", "Parked"), ("rejected", "Rejected")) if by.get(o)]
    return "Statement written by code (the Moderator did not answer). " + " ".join(parts)


def write_statement(runtime: AgentRuntime, rows: list[dict]) -> tuple[str, dict[str, str], bool]:
    """Returns (statement, guardrails for selected_with_condition subjects, written_by_moderator)."""
    conditional = {r["subject"] for r in rows if r["outcome"] == "selected_with_condition"}
    try:
        d = runtime.ask("moderator", (PROMPTS / "statement.md").read_text(encoding="utf-8"),
                        f"{BOARD_MARKER}\n{json.dumps(rows, ensure_ascii=False, indent=1)}", StatementDraft)
        statement, guards, by_model = d.statement, {s: g for s, g in d.guardrails.items() if s in conditional}, True
    except AgentError:
        statement, guards, by_model = fallback_statement(rows), {}, False
    for r in rows:                                   # a guardrail for every conditional outcome, from the votes if needed
        if r["subject"] in conditional and r["subject"] not in guards:
            conds = Counter(v["condition"] for v in r["votes"] if v["condition"])
            guards[r["subject"]] = conds.most_common(1)[0][0] if conds else "Revisit at the end of the pilot."
    return statement, guards, by_model


def overall(decisions: list[Decision]) -> Optional[float]:
    return stage_agreement(decisions)
