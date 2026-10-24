"""R1 · Shortlist. Framework 'applies when' rules evaluated against the fact sheet, in code.

Rule forms (YAML):
  {always: true}
  {fact: team_size, lte: 12}                 # also gte, equals, in
  {fact: card_payments, equals: true, status: confirmed}
  {all: [rule, ...]}  /  {any: [rule, ...]}

Result of a rule is True, False or None (a needed fact is missing: unknown).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.config import load_dir
from app.schemas import FactSheet, FactStatus


@dataclass
class RuleResult:
    value: Optional[bool]
    facts_used: list[str] = field(default_factory=list)
    assumed: bool = False                         # depends on an assumed or unverified fact


def evaluate(rule: dict, sheet: FactSheet) -> RuleResult:
    if not rule:
        return RuleResult(False)
    if rule.get("always"):
        return RuleResult(True)
    if "all" in rule or "any" in rule:
        subs = [evaluate(r, sheet) for r in rule.get("all", rule.get("any", []))]
        used = [f for s in subs for f in s.facts_used]
        assumed = any(s.assumed for s in subs)
        vals = [s.value for s in subs]
        if "all" in rule:
            v = False if False in vals else (None if None in vals else True)
        else:
            v = True if True in vals else (None if None in vals else False)
        return RuleResult(v, used, assumed)
    fact = sheet.get(rule["fact"])
    if fact is None:
        return RuleResult(None)
    if rule.get("status") == "confirmed" and fact.status != FactStatus.confirmed:
        return RuleResult(False, [fact.id], True)
    val = fact.value
    if "equals" in rule:
        ok = val == rule["equals"]
    elif "in" in rule:
        ok = val in rule["in"]
    elif "lte" in rule:
        ok = isinstance(val, (int, float)) and val <= rule["lte"]
    elif "gte" in rule:
        ok = isinstance(val, (int, float)) and val >= rule["gte"]
    else:
        raise ValueError(f"rule has no operator: {rule}")
    return RuleResult(ok, [fact.id], fact.status != FactStatus.confirmed)


class Applicability(str, Enum):
    binding = "binding"
    candidate = "candidate"
    needs_fact = "needs_fact"          # a needed fact is missing: goes to the gray area
    not_applicable = "not_applicable"


@dataclass
class ShortlistItem:
    id: str
    name: str
    status: Applicability
    reason: str
    facts_used: list[str]
    depends_on_assumption: bool = False


def shortlist(sheet: FactSheet, frameworks: Optional[list[dict]] = None) -> list[ShortlistItem]:
    frameworks = frameworks if frameworks is not None else load_dir("frameworks")
    out = []
    for fw in frameworks:
        na = evaluate(fw.get("not_applicable_when", {}), sheet) if fw.get("not_applicable_when") else RuleResult(False)
        if na.value:
            out.append(ShortlistItem(fw["id"], fw["name"], Applicability.not_applicable,
                                     "Excluded by its not-applicable rule", na.facts_used, na.assumed))
            continue
        if fw.get("binding_when"):
            b = evaluate(fw["binding_when"], sheet)
            if b.value:
                out.append(ShortlistItem(fw["id"], fw["name"], Applicability.binding,
                                         "Binding: triggered by confirmed facts", b.facts_used))
                continue
        a = evaluate(fw.get("applies_when", {}), sheet)
        if a.value is True:
            out.append(ShortlistItem(fw["id"], fw["name"], Applicability.candidate,
                                     "Applies-when rule matched" + (" (relies on an assumption)" if a.assumed else ""),
                                     a.facts_used, a.assumed))
        elif a.value is None:
            out.append(ShortlistItem(fw["id"], fw["name"], Applicability.needs_fact,
                                     "A fact this rule needs is missing from the PRD", a.facts_used, True))
        else:
            out.append(ShortlistItem(fw["id"], fw["name"], Applicability.not_applicable,
                                     "Applies-when rule did not match", a.facts_used, a.assumed))
    return out
