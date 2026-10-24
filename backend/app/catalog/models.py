"""Validation for the framework and solution catalogs, so a typo in YAML fails loudly."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, field_validator

from app.config import config, load_dir

FRAMEWORK_KINDS = {"cloud_framework", "practice", "diagram_standard", "doc_format", "method",
                   "pattern", "compliance", "security_standard"}
OPS = {"equals", "in", "lte", "gte"}


def check_rule(rule: dict, vocab: set[str], where: str) -> list[str]:
    errs: list[str] = []
    if not isinstance(rule, dict) or not rule:
        return [f"{where}: rule must be a non-empty mapping"]
    if rule.get("always") is True:
        return errs
    for key in ("all", "any"):
        if key in rule:
            for i, r in enumerate(rule[key]):
                errs += check_rule(r, vocab, f"{where}.{key}[{i}]")
            return errs
    if "fact" not in rule:
        return [f"{where}: needs 'fact', 'all', 'any' or 'always'"]
    if rule["fact"] not in vocab:
        errs.append(f"{where}: unknown fact key '{rule['fact']}'")
    if not OPS & set(rule):
        errs.append(f"{where}: needs one of {sorted(OPS)}")
    return errs


class Source(BaseModel):
    url: str
    title: str
    kind: Literal["official_docs", "case_study"]
    verified: bool = False


class Framework(BaseModel):
    id: str
    name: str
    kind: str
    summary: str
    applies_when: dict
    not_applicable_when: Optional[dict] = None
    binding_when: Optional[dict] = None
    conflicts_with: list[str] = []
    team_cost: Literal["low", "medium", "high"]
    sources: list[Source]

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in FRAMEWORK_KINDS:
            raise ValueError(f"kind must be one of {sorted(FRAMEWORK_KINDS)}")
        return v


PAGE_KINDS = {"official", "pricing", "terms", "sla"}


class Candidate(BaseModel):
    id: str
    name: str
    type: Literal["owned", "cloud_managed", "saas", "open_source", "none"]
    provider: Optional[str] = None
    licence: Optional[str] = None
    lifecycle: Optional[Literal["ga", "preview", "deprecated", "unknown"]] = None
    sla: Literal[True, False, "contract", "unknown", None] = None
    official_api: Literal[True, False, "unknown", None] = None
    data_terms: Optional[Literal["ok", "review", "unknown"]] = None
    maintained: Any = None
    repo: Optional[str] = None            # owner/name on GitHub
    model: Optional[str] = None           # Hugging Face model id
    pages: dict[str, str] = {}
    note: Optional[str] = None

    def page_problems(self) -> list[str]:
        """Pages the gate needs (see config/solutions/_schema.md) that are missing or off the allowlist."""
        from app.knowledge.crawler import allowed
        if self.type in ("none", "owned"):
            return []
        need = {"official", "terms"} | ({"pricing"} if self.type in ("cloud_managed", "saas") else set()) \
            | ({"sla"} if self.sla is True else set())
        errs = [f"missing {k} page" for k in sorted(need - set(self.pages))]
        errs += [f"unknown page kind '{k}'" for k in sorted(set(self.pages) - PAGE_KINDS)]
        errs += [f"{k} page not on the crawl allowlist: {u}" for k, u in self.pages.items() if not allowed(u)]
        return errs


class Capability(BaseModel):
    capability: str
    description: str
    candidates: list[Candidate]


def validate_catalogs() -> list[str]:
    """Return a list of human-readable problems; empty list means everything is valid."""
    vocab = set(config("fact_vocabulary")["facts"])
    errs: list[str] = []
    ids = set()
    for raw in load_dir("frameworks"):
        try:
            fw = Framework.model_validate(raw)
        except Exception as e:
            errs.append(f"framework {raw.get('id', '?')}: {e}")
            continue
        ids.add(fw.id)
        for field in ("applies_when", "not_applicable_when", "binding_when"):
            rule = getattr(fw, field)
            if rule is not None:
                errs += check_rule(rule, vocab, f"{fw.id}.{field}")
        if not fw.sources:
            errs.append(f"{fw.id}: needs at least one source")
    for raw in load_dir("frameworks"):
        for c in raw.get("conflicts_with", []):
            if c not in ids:
                errs.append(f"{raw['id']}: conflicts_with unknown framework '{c}'")
    seen: set[str] = set()
    for raw in load_dir("solutions"):
        try:
            cap = Capability.model_validate(raw)
        except Exception as e:
            errs.append(f"capability {raw.get('capability', '?')}: {e}")
            continue
        for c in cap.candidates:
            if c.id in seen:
                errs.append(f"{cap.capability}/{c.id}: candidate id used twice")
            seen.add(c.id)
            errs += [f"{cap.capability}/{c.id}: {p}" for p in c.page_problems()]
    for fw in load_dir("frameworks"):
        from app.knowledge.crawler import allowed
        errs += [f"{fw['id']}: source not on the crawl allowlist: {s['url']}" for s in fw.get("sources", []) if not allowed(s["url"])]
    return errs
