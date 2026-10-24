"""Shared data contracts. Every agent turn, fact and event is validated against these models."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class FactStatus(str, Enum):
    confirmed = "confirmed"      # quote found on the cited page of the PRD
    assumed = "assumed"          # not stated in the PRD; must go to the gray area
    unverified = "unverified"    # model claimed a quote that could not be matched


class Fact(BaseModel):
    id: str                                  # F-01, F-02, ...
    key: str                                 # from config/fact_vocabulary.yaml
    value: Any
    quote: Optional[str] = None              # exact words from the PRD
    page: Optional[int] = None
    status: FactStatus = FactStatus.unverified
    note: Optional[str] = None


class FactSheet(BaseModel):
    document: str
    facts: list[Fact] = Field(default_factory=list)

    def get(self, key: str) -> Optional[Fact]:
        for f in self.facts:
            if f.key == key:
                return f
        return None


class CitationKind(str, Enum):
    prd_fact = "prd_fact"
    source = "source"            # crawled page from the allowlist
    precedent = "precedent"      # decision database record
    org_policy = "org_policy"


class Citation(BaseModel):
    kind: CitationKind
    ref: str                     # fact id, source id, decision id or policy id
    quote: Optional[str] = None  # under 15 words

    @model_validator(mode="before")
    @classmethod
    def _lenient(cls, v: Any) -> Any:
        """Models write citations as "src-x-1", {"id": ...} or with kind "official_docs". Accept the shape;
        the kind is inferred from the ref, and code checks every ref against the retrieved set afterwards."""
        if isinstance(v, str):
            v = {"ref": v}
        if not isinstance(v, dict):
            return v
        ref = str(v.get("ref") or v.get("id") or v.get("source_id") or v.get("fact_id") or "")
        kind = v.get("kind")
        if kind not in {k.value for k in CitationKind}:
            kind = ("prd_fact" if ref.startswith("F-") else "precedent" if ref.startswith("dec-")
                    else "org_policy" if ref.startswith("pol-") else "source")
        return {**v, "ref": ref, "kind": kind}


class Stance(str, Enum):
    adopt = "adopt"
    adopt_with_condition = "adopt_with_condition"
    reject = "reject"


class RejectedAlternative(BaseModel):
    name: str
    reason: str


class ArgumentCard(BaseModel):
    """One agent's argument about one subject (a framework, build approach, delivery path)."""
    agent: str
    round: Literal["R2", "R4", "R5"] = "R2"
    subject: str
    stance: Stance
    claim: str
    facts: list[str] = Field(default_factory=list)          # fact ids
    citations: list[Citation] = Field(default_factory=list)
    benefit: Optional[str] = None
    cost: Optional[str] = None
    condition: Optional[str] = None                          # required when stance is adopt_with_condition
    rejected_alternative: Optional[RejectedAlternative] = None
    id: Optional[str] = None                                 # set by code, e.g. "architect:azure_waf"
    issues: list[str] = Field(default_factory=list)          # set by code: what the card check found
    weight: Optional[float] = None                           # set by R3: sum of its citations' evidence weights
    removed: bool = False                                    # set by R3: a citation contradicts the claim
    conceded: bool = False                                   # set by R5: its author conceded the challenge
    thinking: Optional[str] = None                           # the agent's own note of what it weighed (shown as its thinking)


class ChallengeType(str, Enum):
    fact = "fact"
    relevance = "relevance"
    evidence = "evidence"
    cost = "cost"
    alternative = "alternative"


class Challenge(BaseModel):
    agent: str
    target_subject: str
    target_agent: str                                       # "" for a counter-case (it targets the whole panel)
    type: ChallengeType
    text: str
    citations: list[Citation] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)          # fact ids
    id: Optional[str] = None                                # set by code: "critic>architect:azure_waf"
    target: Optional[str] = None                            # card id, or "counter:<subject>"
    counter_case: bool = False                              # argues against a unanimous position
    side: Literal["for", "against"] = "against"             # which way it pushes the subject
    weight: Optional[float] = None                          # set by the fact check, as for cards
    removed: bool = False
    issues: list[str] = Field(default_factory=list)
    answered: bool = False                                  # set by R5: rebutted with evidence that carries weight
    thinking: Optional[str] = None                           # the agent's own note of what it weighed (shown as its thinking)


class Rebuttal(BaseModel):
    """R5 · the author's answer to one challenge."""
    agent: str
    challenge: str                                          # challenge id
    target: str                                             # card id, or "counter:<subject>"
    subject: str
    response: Literal["rebut", "concede", "revise"]         # revise: build approach / delivery path only
    text: str
    revised_claim: Optional[str] = None                     # revise: the proposal that replaces the card's claim
    revised_condition: Optional[str] = None
    facts: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    side: Literal["for", "against"] = "for"                 # the side of the card it defends
    id: Optional[str] = None                                # set by code: "re:<challenge id>"
    thinking: Optional[str] = None                           # the agent's own note of what it weighed (shown as its thinking)
    weight: Optional[float] = None
    removed: bool = False
    issues: list[str] = Field(default_factory=list)


class Vote(BaseModel):
    agent: str
    subject: str
    stance: Stance
    confidence: int = Field(ge=1, le=5)
    convinced_by: str                        # the argument that decided this vote
    condition: Optional[str] = None          # for adopt_with_condition: the guardrail the voter wants
    issues: list[str] = Field(default_factory=list)   # set by code: what the vote check found
    thinking: Optional[str] = None                           # the agent's own note of what it weighed (shown as its thinking)


class Verdict(str, Enum):
    verified = "verified"
    partly_supports = "partly_supports"
    unverified = "unverified"
    contradicted = "contradicted"


class CitationCheck(BaseModel):
    """R3 · one citation on one card, checked."""
    card: str                    # card id, e.g. "architect:azure_waf"
    ref: str                     # fact id or source id
    kind: CitationKind
    side: Literal["for", "against"]
    source: str                  # key in evidence_weights.strength: prd_fact, official_docs, ...
    verdict: Verdict
    weight: Optional[float]      # None: contradicted, removed
    by: Literal["code", "judge"] # who decided the verdict
    note: Optional[str] = None
