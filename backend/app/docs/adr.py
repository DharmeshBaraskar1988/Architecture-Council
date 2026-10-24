"""Strategy ADR: the decision document a Stage 0 run produces (task 1.17).

Written from the run's own records only (fact sheet, cards, challenges, decision board), so every
line traces back to an event. Numbers are copied from the consensus engine, never recomputed here.
The reviewer's sign-off is appended when it happens (`with_signoff`).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

OUTCOME = {"selected": "Selected", "selected_with_condition": "Selected with condition",
           "reviewer_decides": "Reviewer decides", "rejected": "Rejected", "parked": "Parked"}
STANCE = {"adopt": "adopt", "adopt_with_condition": "adopt with condition", "reject": "reject"}
NAMES = {"strategist": "Tara (Strategist)", "architect": "Ada (Architect)", "platform_cost": "Kabir (Platform & Cost)",
         "critic": "Rex (Critic)", "moderator": "Mira (Moderator)", "fact_checker": "Vera (Fact checker)"}


def _cell(x: object) -> str:
    """Text safe inside a Markdown table cell: one line, no column breaks."""
    return " ".join(str(x).split()).replace("|", "/")


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{round(x)}%"


VERDICT = {"production_eligible": "production-eligible", "poc_only": "POC only", "rejected": "rejected",
           "needs_verification": "not yet verified", "no_native_service": "no native service"}


def _solutions(gate: dict) -> list[str]:
    """The solution gate in short: what may go to production per capability, and the swap plan for
    every POC-only part (task 1.10)."""
    from app.catalog.gate import swap_plans
    out = ["## Solution gate and swap plans", "",
           "| Capability | Production-eligible | POC only | Rejected |", "|---|---|---|---|"]
    for cap, rows in gate.items():
        pick = lambda v: ", ".join(r["name"] for r in rows if r["verdict"] == v) or "—"   # noqa: E731
        out.append(f"| {cap.replace('_', ' ')} | {_cell(pick('production_eligible'))} | {_cell(pick('poc_only'))} | "
                   f"{_cell(pick('rejected'))} |")
    plans = swap_plans(gate)
    if plans:
        out += ["", "Every POC-only part has a swap plan before production:", ""]
        out += [f"- {p['capability'].replace('_', ' ')}: {p['poc']} ({p['why_poc']}) → "
                f"{', '.join(p['swap_to']) or p['note']}" for p in plans]
    out += ["", "Verdicts come from the production gate (code): licence policy, lifecycle, SLA, official API, "
            "data-use terms and maintenance, with each candidate's official pages fetched as evidence.", ""]
    return out


def _precedents(precedents: dict) -> list[str]:
    if not precedents:
        return []
    out = ["## Precedents considered", "", "| Decision | Project | Outcome | Context match | Counted |", "|---|---|---|---|---|"]
    for pid, p in precedents.items():
        out.append(f"| {pid} | {_cell(p['project'])} | {OUTCOME.get(p['outcome'], p['outcome'])} | "
                   f"{round(p['context'] * 100)}% | {'no (sample)' if p['is_sample'] else 'yes'} |")
    return out + [""]


def strategy_adr(document: str, facts: list[dict], decision: dict, cards: list[dict],
                 challenges: list[dict], names: dict[str, str], when: Optional[str] = None,
                 gate: Optional[dict] = None, precedents: Optional[dict] = None) -> str:
    rows = decision["board"]
    nm = lambda s: names.get(s, s)                                                    # noqa: E731
    by = {o: [r for r in rows if r["outcome"] == o] for o in OUTCOME}
    out = [f"# Strategy decision: {document}", "",
           f"Architecture Council, Stage 0 (strategy) · {when or date.today().isoformat()} · "
           f"stage agreement {_pct(decision.get('stage_agreement'))}", "",
           "## Position statement", "", decision.get("statement", ""), ""]

    out += ["## Decisions", "",
            "| Subject | Outcome | Agreement | Vote | Evidence | Condition or reason |", "|---|---|---|---|---|---|"]
    for r in rows:
        why = r.get("guardrail") or (r["reasons"][-1] if r.get("reasons") else "")
        out.append(f"| {_cell(r.get('name') or nm(r['subject']))} | {OUTCOME.get(r['outcome'], r['outcome'])}"
                   f"{' (re-voted)' if r.get('revoted') else ''} | {_pct(r.get('agreement'))} | {_pct(r.get('vote_support'))} | "
                   f"{_pct(r.get('evidence_balance'))} | {_cell(why)} |")
    out += ["", "Agreement = 0.6 × vote + 0.4 × evidence, computed by code from the votes and the fact-checked evidence. "
            "Binding subjects (org policy or a confirmed compliance fact) are selected by rule.", ""]

    def lead(subject: str, title: str) -> None:
        c = next((c for c in cards if c["subject"] == subject and not c.get("removed")), None)
        r = next((r for r in rows if r["subject"] == subject), None)
        if not c:
            return
        out.extend([f"## {title}", "", c["claim"], ""])
        if c.get("condition"):
            out.extend([f"Condition proposed: {c['condition']}", ""])
        if r:
            out.extend([f"Outcome: **{OUTCOME.get(r['outcome'], r['outcome'])}** ({_pct(r.get('agreement'))})"
                        + (f". Guardrail: {r['guardrail']}" if r.get("guardrail") else ""), ""])
    lead("build_approach", "Build approach")
    lead("delivery_path", "Delivery path")

    open_items = by["reviewer_decides"] + by["parked"]
    if open_items:
        out += ["## Open for the reviewer", ""]
        for r in open_items:
            out.append(f"- **{r.get('name') or nm(r['subject'])}** ({_pct(r.get('agreement'))}): "
                       f"{r['reasons'][-1] if r.get('reasons') else ''}")
            for o in r.get("open_objections", [])[:2]:
                out.append(f"  - Open objection: {o}")
        out.append("")

    alts = [c for c in cards if c.get("rejected_alternative")]
    rejected = by["rejected"]
    if alts or rejected:
        out += ["## Rejected options", ""]
        for r in rejected:
            out.append(f"- **{r.get('name') or nm(r['subject'])}**: rejected by the panel ({_pct(r.get('agreement'))}).")
        seen = set()
        for c in alts:
            a = c["rejected_alternative"]
            key = (a["name"].lower(), c["subject"])
            if key in seen:
                continue
            seen.add(key)
            out.append(f"- {a['name']} (instead of {nm(c['subject'])}), per {NAMES.get(c['agent'], c['agent'])}: {a['reason']}")
        out.append("")

    if gate:
        out += _solutions(gate)
    out += _precedents(precedents or {})

    out += ["## Context: facts from the document", "", "| Id | Fact | Value | Status | Source |", "|---|---|---|---|---|"]
    for f in facts:
        src = f"p.{f['page']}: “{f['quote']}”" if f.get("quote") else (f.get("note") or "")
        out.append(f"| {f['id']} | {f['key'].replace('_', ' ')} | {_cell(f['value'])} | {f['status']} | {_cell(src)} |")
    out += ["", "Every confirmed fact's quote was matched against the document by code. Assumed facts are not evidence.", ""]

    strong = sorted((c for c in challenges if not c.get("removed") and (c.get("weight") or 0) > 0),
                    key=lambda c: -(c.get("weight") or 0))[:6]
    if strong:
        out += ["## Strongest objections raised", ""]
        for c in strong:
            out.append(f"- {NAMES.get(c['agent'], c['agent'])} on {nm(c['target_subject'])} ({c['type']}, weight {c['weight']}"
                       f"{', answered' if c.get('answered') else ', not answered'}): {c['text']}")
        out.append("")
    out += ["## Reviewer sign-off", "", "_Pending._", ""]
    return "\n".join(out)


def with_signoff(adr: str, review: dict, notes: list[dict]) -> str:
    """Replace the pending sign-off with the reviewer's decision and notes."""
    verdict = "Approved" if review.get("decision") == "approve" else "Overridden"
    lines = [f"**{verdict}** by {review.get('reviewer', 'reviewer')}" + (" (automatic)" if review.get("auto") else "") + "."]
    if review.get("reason"):
        lines.append(f"Reason: {review['reason']}")
    if notes:
        lines += ["", "Notes raised during the session:"] + [f"- {n['text']}" for n in notes]
    return adr.replace("## Reviewer sign-off\n\n_Pending._", "## Reviewer sign-off\n\n" + "\n".join(lines))
