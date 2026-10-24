"""Production gate: can this candidate be used in production, only in a POC, or not at all?

Decides from the fields recorded in config/solutions/*.yaml, overridden by what the live verifier
fetched (`council verify`, app/catalog/verify.py): licence and maintenance from GitHub or Hugging
Face, preview from the official page, and `verified` only when every listed page is stored.

Precedence: rejected > poc_only > needs_verification > production_eligible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.config import config, load_dir


class GateVerdict(str, Enum):
    production_eligible = "production_eligible"
    poc_only = "poc_only"
    needs_verification = "needs_verification"
    rejected = "rejected"
    no_native_service = "no_native_service"


_RANK = {GateVerdict.production_eligible: 0, GateVerdict.needs_verification: 1,
         GateVerdict.poc_only: 2, GateVerdict.rejected: 3}


@dataclass
class GateResult:
    id: str
    name: str
    type: str
    verdict: GateVerdict
    reasons: list[str] = field(default_factory=list)
    provider: Optional[str] = None
    evidence: list[str] = field(default_factory=list)      # pages and APIs the verdict rests on
    checked_at: Optional[str] = None


def check_licence(spdx: str, is_model: bool = False) -> tuple[GateVerdict, str]:
    pol = config("license_policy")
    if spdx in (None, "", "unknown"):
        return GateVerdict.needs_verification, "Licence not yet identified"
    if spdx == "proprietary":
        return GateVerdict.production_eligible, "Commercial service under vendor terms"
    if spdx in pol.get("blocked", []):
        return GateVerdict.rejected, f"Licence {spdx} is blocked by policy"
    if any(m.lower() in spdx.lower() for m in pol.get("non_commercial_markers", [])):
        return GateVerdict.poc_only, f"Licence {spdx} does not allow commercial use"
    if spdx in pol.get("review_needed", []):
        return GateVerdict.poc_only, f"Licence {spdx} needs legal review before production"
    if is_model and spdx not in pol.get("model_licences_allowed", []):
        return GateVerdict.poc_only, f"Model licence {spdx} is a custom licence: legal review before production"
    if spdx in pol.get("allowed", []):
        return GateVerdict.production_eligible, f"Licence {spdx} allows commercial use"
    return GateVerdict.needs_verification, f"Licence {spdx} is not in the licence policy"


def gate(c: dict, verification: Optional[dict] = None) -> GateResult:
    """Gate one candidate. `verification` is its entry from data/catalog/verification.json, if any."""
    ctype = c.get("type", "unknown")
    v = verification or {}
    c = {**c, **v.get("overrides", {}), "verified": v.get("verified", c.get("verified", False))}
    evidence = [p["url"] for p in v.get("pages", {}).values() if p.get("ok")] + \
               [s["url"] for s in v.get("signals", {}).values() if s.get("url") and not s.get("error")]
    res = GateResult(c["id"], c.get("name", c["id"]), ctype, GateVerdict.production_eligible,
                     provider=c.get("provider"), evidence=evidence, checked_at=v.get("checked_at"))
    if ctype == "none":
        res.verdict = GateVerdict.no_native_service
        res.reasons.append("No native service on this provider")
        return res
    if ctype == "owned":
        res.reasons.append(f"Already owned by the company: {c.get('note') or 'existing stack'}")
        return res

    checks: list[tuple[GateVerdict, str]] = [check_licence(c.get("licence"), is_model=bool(c.get("model")))]

    lc = c.get("lifecycle", "unknown")
    checks.append({"ga": (GateVerdict.production_eligible, "Generally available"),
                   "preview": (GateVerdict.poc_only, "Preview: no production support"),
                   "deprecated": (GateVerdict.rejected, "Deprecated")}.get(lc, (GateVerdict.needs_verification, "Lifecycle not yet checked")))

    if c.get("official_api") is False:
        checks.append((GateVerdict.poc_only, "No official API agreement for this use"))
    elif c.get("official_api") is not True:
        checks.append((GateVerdict.needs_verification, "Official API status not yet checked"))

    if ctype in ("cloud_managed", "saas"):
        sla = c.get("sla", "unknown")
        if sla is False:
            checks.append((GateVerdict.poc_only, "No published SLA"))
        elif sla == "contract":
            checks.append((GateVerdict.poc_only, "SLA only in an enterprise contract: production needs that contract signed"))
        elif sla is not True:
            checks.append((GateVerdict.needs_verification, "SLA not yet checked"))

    dt = c.get("data_terms", "unknown")
    if dt == "review":
        checks.append((GateVerdict.poc_only, "Data-use terms need review"))
    elif dt != "ok":
        checks.append((GateVerdict.needs_verification, "Data-use terms not yet checked"))

    if ctype == "open_source":
        m = c.get("maintained", "unknown")
        if m is False:
            checks.append((GateVerdict.poc_only, "Not actively maintained (archived or no push in 12 months)"))
        elif m is not True:
            checks.append((GateVerdict.needs_verification, "Maintenance not yet checked"))

    if not c.get("verified"):
        why = "; ".join(v.get("notes", [])) if v else "run `council verify`"
        checks.append((GateVerdict.needs_verification, f"Evidence not yet fetched and checked ({why})"))

    worst = max(checks, key=lambda x: _RANK[x[0]])[0]
    res.verdict = worst
    res.reasons = [r for v_, r in checks if v_ != GateVerdict.production_eligible] or [r for _, r in checks]
    if v.get("notes") and c.get("verified"):
        res.reasons += [n for n in v["notes"] if n not in res.reasons]
    return res


def owned_candidates(capability: str) -> list[dict]:
    """What the company already owns for this capability (config/policies/existing_stack.yaml, task 1.13)."""
    out = []
    for n, item in enumerate(config("policies/existing_stack").get("owned") or [], 1):
        if capability in (item.get("capabilities") or []):
            out.append({"id": f"owned_{n}_{capability}", "name": item["name"], "type": "owned",
                        "provider": item.get("provider"), "note": item.get("note") or "listed in the existing stack"})
    return out


def gate_catalog() -> dict[str, list[GateResult]]:
    from app.catalog.verify import load
    ver = load()
    out = {}
    for cap in load_dir("solutions"):
        out[cap["capability"]] = [gate(c) for c in owned_candidates(cap["capability"])] + \
                                 [gate(c, ver.get(c["id"])) for c in cap.get("candidates", [])]
    return out


def swap_plans(gate: dict[str, list[dict]]) -> list[dict]:
    """For every POC-only candidate, the production-eligible options to move to before production:
    already owned first, then the same provider, then the rest. Works on the JSON form of the gate."""
    plans = []
    for cap, rows in gate.items():
        ready = [r for r in rows if r["verdict"] == GateVerdict.production_eligible.value]
        for r in rows:
            if r["verdict"] != GateVerdict.poc_only.value:
                continue
            order = sorted(ready, key=lambda x: (x["type"] != "owned", x.get("provider") != r.get("provider")))
            plans.append({"capability": cap, "poc": r["name"], "why_poc": r["reasons"][0] if r["reasons"] else "",
                          "swap_to": [x["name"] for x in order[:3]],
                          "note": "" if order else "No production-eligible option in the catalog yet: production waits for one"})
    return plans
