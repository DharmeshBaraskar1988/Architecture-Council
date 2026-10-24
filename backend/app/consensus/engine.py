"""Consensus engine: turns votes and surviving evidence into an agreement % and an outcome.

    V = Σ(confidence × stance value) ÷ Σ confidence
    E = W_for ÷ (W_for + W_against),  W = strength × relevance × verified factor
    A = vote_weight × V + evidence_weight × E

Pure functions only: the same inputs always give the same decision. Settings in config/consensus.yaml
and config/evidence_weights.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.config import config
from app.schemas import Stance, Verdict, Vote


class Outcome(str, Enum):
    selected = "selected"
    selected_with_condition = "selected_with_condition"
    reviewer_decides = "reviewer_decides"
    rejected = "rejected"
    parked = "parked"
    not_applicable = "not_applicable"


@dataclass
class Evidence:
    side: str                         # "for" or "against"
    source: str                       # key in evidence_weights.strength, e.g. prd_fact, case_study
    verdict: Verdict = Verdict.verified
    relevance: float = 1.0            # context match 0..1
    answered: bool = False            # for "against": was it rebutted with evidence?
    label: str = ""


@dataclass
class Decision:
    subject: str
    outcome: Outcome
    agreement: Optional[float]        # 0..100, None when not computed (parked, not applicable)
    vote_support: Optional[float]
    evidence_balance: Optional[float]
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def _cfg():
    return config("consensus"), config("evidence_weights")


def vote_support(votes: list[Vote]) -> float:
    c, _ = _cfg()
    values = c["stance_values"]
    total = sum(v.confidence for v in votes)
    if total == 0:
        return 0.0
    return sum(v.confidence * values[v.stance.value] for v in votes) / total


def evidence_weight(ev: Evidence) -> Optional[float]:
    """Weight of one argument; None means it is removed (contradicted)."""
    _, w = _cfg()
    factor = w["verified_factor"][ev.verdict.value]
    if factor == "remove":
        return None
    strength = w["strength"].get(ev.source, 0)
    if strength == "binding":
        strength = 3
    return float(strength) * max(0.0, min(1.0, ev.relevance)) * float(factor)


def evidence_balance(evidence: list[Evidence]) -> tuple[float, list[str]]:
    w_for = w_against = 0.0
    notes = []
    for ev in evidence:
        wt = evidence_weight(ev)
        if wt is None:
            notes.append(f"Removed contradicted argument: {ev.label or ev.source}")
            continue
        if ev.side == "for":
            w_for += wt
        else:
            w_against += wt
    if w_for + w_against == 0:
        notes.append("No weighted evidence on either side; evidence counted as neutral (50%)")
        return 0.5, notes
    return w_for / (w_for + w_against), notes


def strong_unanswered(evidence: list[Evidence], strong_at: float = 2.0) -> list[Evidence]:
    out = []
    for ev in evidence:
        wt = evidence_weight(ev)
        if ev.side == "against" and not ev.answered and wt is not None and wt >= strong_at:
            out.append(ev)
    return out


def outcome_for(agreement_pct: float) -> Outcome:
    t = config("consensus")["thresholds"]
    if agreement_pct >= t["selected"]:
        return Outcome.selected
    if agreement_pct >= t["selected_with_condition"]:
        return Outcome.selected_with_condition
    if agreement_pct >= t["reviewer_decides"]:
        return Outcome.reviewer_decides
    return Outcome.rejected


def decide(subject: str, votes: list[Vote], evidence: list[Evidence], *,
           binding: bool = False, key_fact_assumed: bool = False,
           not_applicable: bool = False, challenged: bool = True) -> Decision:
    if not_applicable:
        return Decision(subject, Outcome.not_applicable, None, None, None,
                        ["Applicability rule did not match the facts"])
    if binding:
        return Decision(subject, Outcome.selected, 100.0, None, None,
                        ["Binding: org policy or a confirmed compliance fact; agents vote only on how to apply it"])
    if key_fact_assumed:
        return Decision(subject, Outcome.parked, None, None, None,
                        ["Depends on an assumed fact; sent to the gray area for the reviewer"])
    c, _ = _cfg()
    V = vote_support(votes)
    E, notes = evidence_balance(evidence)
    A = 100 * (c["vote_weight"] * V + c["evidence_weight"] * E)
    A = round(A, 1)
    out = outcome_for(A)
    reasons = [f"Vote {V*100:.0f}% · Evidence {E*100:.0f}% → agreement {A:.0f}%"] + notes
    flags = []
    blockers = strong_unanswered(evidence)
    if blockers and out in (Outcome.selected, Outcome.selected_with_condition):
        out = Outcome.reviewer_decides
        reasons.append("Capped at reviewer decides: strong objection not answered (" +
                       "; ".join(b.label or b.source for b in blockers) + ")")
    if not challenged:
        flags.append("untested_consensus: the Critic must state a counter-case before this is final")
    return Decision(subject, out, A, round(V * 100, 1), round(E * 100, 1), reasons, flags)


def stage_agreement(decisions: list[Decision], impact: Optional[dict[str, float]] = None) -> Optional[float]:
    """Impact-weighted mean agreement over decided subjects (parked / not applicable excluded)."""
    impact = impact or {}
    pairs = [(d.agreement, impact.get(d.subject, 1.0)) for d in decisions if d.agreement is not None]
    if not pairs:
        return None
    total = sum(w for _, w in pairs)
    return round(sum(a * w for a, w in pairs) / total, 1)
