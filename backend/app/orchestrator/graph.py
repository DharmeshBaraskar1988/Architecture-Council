"""Stage 0 orchestration with LangGraph.

LangGraph only decides the ORDER of steps, pauses for the human reviewer, and keeps a
checkpoint so a session can resume. Every decision is still made by the plain, tested
functions it calls (fact sheet, shortlist, gate, consensus).

    START → R0 fact sheet → R1 shortlist + gate ─┬→ R2 propose (one branch per voter, blind) ─┬→ R2 check
                                                 └→ ...                                      ┘
          → R3 fact check ─┬→ R4 challenge (one branch per challenger) ─┬→ R4 check + fact check
                           └→ ...                                       ┘
          → R5 rebut (one branch per challenged author) → R5 check + fact check
          → R6 vote (one branch per voter, blind) → R6 check
          → R7 tally ─┬→ (split 40–59%) compromise → re-vote (one branch per voter) ─┬→ R7 final → reviewer gate → END
                      └──────────────────────────────────────────────────────────────┘

The reviewer gate uses `interrupt()`: the run pauses, the CLI (later the viewer) shows the
result, and the run resumes with the reviewer's answer via `Command(resume=...)`.
"""
from __future__ import annotations

import json
import operator
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from app.agents.runtime import AgentError, AgentRuntime
from app.config import config
from app.catalog.gate import gate_catalog, swap_plans
from app.catalog.rules import shortlist
from app.debate import challenges, converge, proposals, rebuttals, votes
from app.docs import adr
from app.factcheck import verdicts
from app.events.bus import EventBus
from app.knowledge.factsheet import build_fact_sheet
from app.knowledge.ingest import load_document
from app.ledger import store as ledger

# Rounds that exist in the plan but are not built yet. Removed from this list as they land.
PENDING_ROUNDS: list[str] = []          # every Stage 0 round is built


class Stage0State(TypedDict, total=False):
    session: str
    prd_path: str
    run_dir: str
    fact_sheet: dict
    shortlist: list[dict]
    gate: dict
    drafts: Annotated[list[dict], operator.add]      # R2 branches append here in parallel
    r2_failures: Annotated[list[dict], operator.add]
    cards: list[dict]
    dropped_cards: list[dict]
    checks: list[dict]
    r3_errors: list[str]
    challenge_drafts: Annotated[list[dict], operator.add]
    r4_failures: Annotated[list[dict], operator.add]
    challenges: list[dict]
    challenge_checks: list[dict]
    untested: list[str]
    rebuttal_drafts: Annotated[list[dict], operator.add]
    r5_failures: Annotated[list[dict], operator.add]
    rebuttals: list[dict]
    rebuttal_checks: list[dict]
    vote_drafts: Annotated[list[dict], operator.add]
    r6_failures: Annotated[list[dict], operator.add]
    votes: list[dict]
    tally: dict
    split: list[str]
    compromises: dict
    revote_drafts: Annotated[list[dict], operator.add]
    r7_failures: Annotated[list[dict], operator.add]
    decision: dict
    final_votes: list[dict]                          # R6 votes with re-voted subjects replaced
    pending_rounds: list[str]
    review: dict
    mode: str                                        # production (default) or poc: what the gate allows
    precedents: dict                                 # citable decision precedents for this document (dec-...)
    recorded: list[str]                              # decision ids written to the decision database


def build_stage0_graph(runtime: AgentRuntime, bus: EventBus, checkpointer: Optional[Any] = None):
    """Compile the Stage 0 graph. Runtime and event bus are passed in, not stored in state,
    so the checkpointed state stays plain JSON."""

    def _sources(state: Stage0State) -> dict:
        """Framework sources and this session's decision precedents: everything an agent may cite."""
        return {**proposals.source_index(), **state.get("precedents", {})}

    def started(rnd: str, agents: list[str], doing: str) -> None:
        """Tell watchers who is working now (the room shows them thinking until their turns arrive)."""
        bus.emit("round.started", "strategy", round=rnd, agents=agents, doing=doing)

    def r0_fact_sheet(state: Stage0State) -> dict:
        doc = load_document(state["prd_path"])
        Path(state["run_dir"], "document.json").write_text(json.dumps(
            {"name": doc.name, "sections": [{"number": pg.number, "title": pg.title, "text": pg.text} for pg in doc.pages]},
            indent=1, ensure_ascii=False), encoding="utf-8")
        bus.emit("session.started", "strategy", document=doc.name, pages=len(doc.pages),
                 sections=[{"number": pg.number, "title": pg.title} for pg in doc.pages])
        # Who sits at the table: role, specialty, rounds, and the LLM each is set to use (main, then backups).
        for agent, p in runtime.personas.items():
            fb = p.get("fallback_model") or []
            bus.emit("agent.introduced", "strategy", agent=agent, name=p["name"], role=p["role"],
                     specialty=p.get("specialty", ""), works_on=p.get("works_on", ""), votes=bool(p.get("votes")),
                     models=[p["model"]] + (fb if isinstance(fb, list) else [fb]))
        started("R0", ["moderator"], "Reading the document and writing down its facts")
        sheet = build_fact_sheet(doc, runtime, bus)
        Path(state["run_dir"], "fact_sheet.json").write_text(sheet.model_dump_json(indent=2), encoding="utf-8")
        return {"fact_sheet": sheet.model_dump(mode="json")}

    def r1_shortlist(state: Stage0State) -> dict:
        started("R1", ["strategist"], "Matching every framework's rules against the facts")
        from app.schemas import FactSheet
        items = [{**asdict(i), "status": i.status.value} for i in shortlist(FactSheet.model_validate(state["fact_sheet"]))]
        bus.emit("shortlist.ready", "strategy", items=items)
        Path(state["run_dir"], "applicability.json").write_text(json.dumps(items, indent=2), encoding="utf-8")
        gate = {cap: [{**asdict(r), "verdict": r.verdict.value} for r in rs] for cap, rs in gate_catalog().items()}
        Path(state["run_dir"], "solution_gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
        Path(state["run_dir"], "swap_plans.json").write_text(json.dumps(swap_plans(gate), indent=2), encoding="utf-8")
        subjects = [i["id"] for i in items if i["status"] in proposals.OPEN_STATUSES] + list(proposals.LEAD_SUBJECTS)
        precedents = ledger.precedent_index(state["fact_sheet"]["facts"], subjects, session=state["session"],
                                            project=state["fact_sheet"]["document"])
        Path(state["run_dir"], "precedents.json").write_text(json.dumps(precedents, indent=2, ensure_ascii=False),
                                                             encoding="utf-8")
        return {"shortlist": items, "gate": gate, "precedents": precedents}

    def r2_fan_out(state: Stage0State) -> list[Send]:
        # Every voter gets the same brief and nothing from the others: that is what keeps R2 blind.
        brief = proposals.build_brief(state["fact_sheet"], state["shortlist"], state["gate"], _sources(state),
                                      state.get("mode", "production"))
        started("R2", proposals.voters(), "Each voter writes a position on every framework, without seeing the others")
        return [Send("r2_propose", {"agent": a, "brief": brief}) for a in proposals.voters()]

    def r2_propose(branch: dict) -> dict:
        try:
            drafts = proposals.propose(branch["agent"], runtime, branch["brief"])
        except AgentError as e:
            return {"r2_failures": [{"agent": branch["agent"], "error": str(e)[:500]}]}
        return {"drafts": [{"agent": branch["agent"], **d.model_dump(mode="json")} for d in drafts]}

    def r2_check(state: Stage0State) -> dict:
        from app.schemas import FactSheet
        sheet, sources = FactSheet.model_validate(state["fact_sheet"]), _sources(state)
        cards, dropped = [], []
        for agent in proposals.voters():                  # fixed order, so the log is the same every run
            mine = [proposals.CardDraft.model_validate({k: v for k, v in d.items() if k != "agent"})
                    for d in state.get("drafts", []) if d["agent"] == agent]
            kept, gone = proposals.check_cards(agent, mine, sheet, state["shortlist"], sources)
            cards += [c.model_dump(mode="json") for c in kept]
            dropped += gone
        for c in cards:
            bus.emit("card.proposed", "strategy", **c)
        for f in state.get("r2_failures", []):
            bus.emit("error", "strategy", round="R2", **f)
        out = {"cards": cards, "dropped": dropped, "failures": state.get("r2_failures", []),
               "missing": proposals.coverage(cards, state["shortlist"], proposals.voters())}
        Path(state["run_dir"], "proposals.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"cards": cards, "dropped_cards": dropped}

    def r3_fact_check(state: Stage0State) -> dict:
        from app.schemas import ArgumentCard, FactSheet
        started("R3", ["fact_checker"], "Checking every citation on every card")
        cards = [ArgumentCard.model_validate(c) for c in state.get("cards", [])]
        cards, checks, errors = verdicts.fact_check(cards, FactSheet.model_validate(state["fact_sheet"]),
                                                    _sources(state), runtime)
        for c in checks:
            bus.emit("factcheck.verdict", "strategy", target=f"{c.card}#{c.ref}", **c.model_dump(mode="json"))
        for e in errors:
            bus.emit("error", "strategy", round="R3", agent="fact_checker", error=e)
        out = {"summary": verdicts.summary(checks), "judge_errors": errors,
               "cards": [{"id": c.id, "weight": c.weight, "removed": c.removed} for c in cards],
               "checks": [c.model_dump(mode="json") for c in checks]}
        Path(state["run_dir"], "factcheck.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"cards": [c.model_dump(mode="json") for c in cards],
                "checks": out["checks"], "r3_errors": errors}

    def _cards(state: Stage0State):
        from app.schemas import ArgumentCard
        return [ArgumentCard.model_validate(c) for c in state.get("cards", [])]

    def r4_fan_out(state: Stage0State):
        cards = _cards(state)
        assigned, _ = challenges.assign(cards, proposals.voters())
        brief = proposals.build_brief(state["fact_sheet"], state["shortlist"], state["gate"], _sources(state),
                                      state.get("mode", "production"))
        sends = [Send("r4_challenge", {"agent": a, "brief": brief,
                                       "targets": challenges.targets_for(ids, cards, state.get("checks", []))})
                 for a, ids in assigned.items() if ids]
        started("R4", [a for a, ids in assigned.items() if ids], "Each challenger studies the cards it must attack")
        return sends or "r4_check"

    def r4_challenge(branch: dict) -> dict:
        try:
            drafts = challenges.challenge(branch["agent"], runtime, branch["brief"], branch["targets"])
        except AgentError as e:
            return {"r4_failures": [{"agent": branch["agent"], "error": str(e)[:500]}]}
        return {"challenge_drafts": [{"agent": branch["agent"], **d.model_dump(mode="json")} for d in drafts]}

    def r4_check(state: Stage0State) -> dict:
        from app.schemas import FactSheet
        cards, sheet, sources = _cards(state), FactSheet.model_validate(state["fact_sheet"]), _sources(state)
        assigned, notes = challenges.assign(cards, proposals.voters())   # same inputs, same assignment as the fan-out
        kept, dropped = [], []
        for agent in proposals.voters():
            mine = [challenges.ChallengeDraft.model_validate({k: v for k, v in d.items() if k != "agent"})
                    for d in state.get("challenge_drafts", []) if d["agent"] == agent]
            k, gone = challenges.check_challenges(agent, mine, assigned[agent], cards, sheet, sources)
            kept += k
            dropped += gone
        weighed, checks, errors = verdicts.fact_check(challenges.as_cards(kept), sheet, sources, runtime)
        kept = [ch.model_copy(update={"weight": w.weight, "removed": w.removed, "issues": w.issues})
                for ch, w in zip(kept, weighed)]
        for ch in kept:
            payload = ch.model_dump(mode="json")
            bus.emit("challenge.raised", "strategy", challenge_type=payload.pop("type"), **payload)
        for c in checks:
            bus.emit("factcheck.verdict", "strategy", target=f"{c.card}#{c.ref}", **c.model_dump(mode="json"))
        failures = state.get("r4_failures", [])
        for f in failures:
            bus.emit("error", "strategy", round="R4", **f)
        for e in errors:
            bus.emit("error", "strategy", round="R4", agent="fact_checker", error=e)
        untested = challenges.untested(cards, kept)
        out = {"assigned": assigned, "assignment_notes": notes, "challenges": [c.model_dump(mode="json") for c in kept],
               "checks": [c.model_dump(mode="json") for c in checks], "dropped": dropped, "failures": failures,
               "unanswered": challenges.unanswered_targets(assigned, kept, {f["agent"] for f in failures}),
               "untested_subjects": untested, "judge_errors": errors}
        Path(state["run_dir"], "challenges.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"challenges": out["challenges"], "challenge_checks": out["checks"], "untested": untested}

    def _challenges(state: Stage0State):
        from app.schemas import Challenge
        return [Challenge.model_validate(c) for c in state.get("challenges", [])]

    def r5_fan_out(state: Stage0State):
        cards, chs = _cards(state), _challenges(state)
        assigned = rebuttals.assign(chs, cards, proposals.voters())
        brief = proposals.build_brief(state["fact_sheet"], state["shortlist"], state["gate"], _sources(state),
                                      state.get("mode", "production"))
        checks = state.get("checks", []) + state.get("challenge_checks", [])
        sends = [Send("r5_rebut", {"agent": a, "brief": brief, "items": rebuttals.items_for(ids, chs, cards, checks)})
                 for a, ids in assigned.items() if ids]
        started("R5", [a for a, ids in assigned.items() if ids], "Each author answers the challenges to their cards")
        return sends or "r5_check"

    def r5_rebut(branch: dict) -> dict:
        try:
            drafts = rebuttals.rebut(branch["agent"], runtime, branch["brief"], branch["items"])
        except AgentError as e:
            return {"r5_failures": [{"agent": branch["agent"], "error": str(e)[:500]}]}
        return {"rebuttal_drafts": [{"agent": branch["agent"], **d.model_dump(mode="json")} for d in drafts]}

    def r5_check(state: Stage0State) -> dict:
        from app.schemas import FactSheet
        cards, chs = _cards(state), _challenges(state)
        sheet, sources = FactSheet.model_validate(state["fact_sheet"]), _sources(state)
        assigned = rebuttals.assign(chs, cards, proposals.voters())      # same inputs, same assignment as the fan-out
        kept, dropped = [], []
        for agent in proposals.voters():
            mine = [rebuttals.RebuttalDraft.model_validate({k: v for k, v in d.items() if k != "agent"})
                    for d in state.get("rebuttal_drafts", []) if d["agent"] == agent]
            k, gone = rebuttals.check_rebuttals(agent, mine, assigned[agent], chs, sheet, sources)
            kept += k
            dropped += gone
        rebut_only = [r for r in kept if r.response != "concede"]        # concessions carry no evidence to weigh
        weighed, checks, errors = verdicts.fact_check(rebuttals.as_cards(rebut_only), sheet, sources, runtime)
        w = {c.id: c for c in weighed}
        kept = [r.model_copy(update={"weight": w[r.id].weight, "removed": w[r.id].removed, "issues": w[r.id].issues})
                if r.id in w else r for r in kept]
        cards, chs = rebuttals.apply(cards, chs, kept)
        for r in kept:
            bus.emit("rebuttal.made", "strategy", **r.model_dump(mode="json"))
        for c in checks:
            bus.emit("factcheck.verdict", "strategy", target=f"{c.card}#{c.ref}", **c.model_dump(mode="json"))
        failures = state.get("r5_failures", [])
        for f in failures:
            bus.emit("error", "strategy", round="R5", **f)
        for e in errors:
            bus.emit("error", "strategy", round="R5", agent="fact_checker", error=e)
        out = {"assigned": assigned, "rebuttals": [r.model_dump(mode="json") for r in kept],
               "checks": [c.model_dump(mode="json") for c in checks], "dropped": dropped, "failures": failures,
               "unanswered": rebuttals.unanswered(assigned, kept, {f["agent"] for f in failures}),
               "conceded_cards": [c.id for c in cards if c.conceded],
               "challenges_answered": [c.id for c in chs if c.answered],
               "challenges_open": [c.id for c in chs if not c.answered and not c.removed],
               "judge_errors": errors}
        Path(state["run_dir"], "rebuttals.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"rebuttals": out["rebuttals"], "rebuttal_checks": out["checks"],
                "cards": [c.model_dump(mode="json") for c in cards], "challenges": [c.model_dump(mode="json") for c in chs]}

    def _ballot(state: Stage0State) -> list[dict]:
        from app.schemas import Rebuttal
        return votes.ballot(state["shortlist"], _cards(state), _challenges(state),
                            [Rebuttal.model_validate(r) for r in state.get("rebuttals", [])])

    def r6_fan_out(state: Stage0State):
        items = _ballot(state)
        if not items:
            return "r6_check"
        # Same ballot for everyone, votes collected only after all are in: that is what keeps R6 blind.
        started("R6", proposals.voters(), "Everyone votes at once, without seeing the others")
        return [Send("r6_vote", {"agent": a, "sheet": state["fact_sheet"], "items": items}) for a in proposals.voters()]

    def r6_vote(branch: dict) -> dict:
        try:
            drafts = votes.vote(branch["agent"], runtime, branch["sheet"], branch["items"])
        except AgentError as e:
            return {"r6_failures": [{"agent": branch["agent"], "error": str(e)[:500]}]}
        return {"vote_drafts": [{"agent": branch["agent"], **d.model_dump(mode="json")} for d in drafts]}

    def r6_check(state: Stage0State) -> dict:
        items = _ballot(state)
        kept, dropped = [], []
        for agent in proposals.voters():
            mine = [votes.VoteDraft.model_validate({k: v for k, v in d.items() if k != "agent"})
                    for d in state.get("vote_drafts", []) if d["agent"] == agent]
            k, gone = votes.check_votes(agent, mine, items)
            kept += k
            dropped += gone
        for v in kept:
            bus.emit("vote.cast", "strategy", **v.model_dump(mode="json"))
        failures = state.get("r6_failures", [])
        for f in failures:
            bus.emit("error", "strategy", round="R6", **f)
        tally = votes.tally(kept, items)
        out = {"ballot": items, "votes": [v.model_dump(mode="json") for v in kept], "tally": tally,
               "dropped": dropped, "failures": failures,
               "abstentions": votes.abstentions(kept, items, proposals.voters(), {f["agent"] for f in failures})}
        Path(state["run_dir"], "votes.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"votes": out["votes"], "tally": tally}

    def _decide(state: Stage0State, vote_list):
        from app.schemas import Rebuttal
        checks = state.get("checks", []) + state.get("challenge_checks", []) + state.get("rebuttal_checks", [])
        return converge.decide_all(_ballot(state), state["shortlist"], vote_list, _cards(state), _challenges(state),
                                   [Rebuttal.model_validate(r) for r in state.get("rebuttals", [])], checks)

    def _votes(state: Stage0State):
        from app.schemas import Vote
        return [Vote.model_validate(v) for v in state.get("votes", [])]

    def r7_tally(state: Stage0State) -> dict:
        split = [d.subject for d in _decide(state, _votes(state)) if converge.needs_revote(d)]
        return {"split": split, "pending_rounds": list(PENDING_ROUNDS)}

    def r7_route(state: Stage0State) -> str:
        return "r7_compromise" if state.get("split") and config("consensus")["caps"]["revotes"] > 0 else "r7_final"

    def r7_compromise(state: Stage0State) -> dict:
        started("R7", ["moderator"], "Looking for a compromise on the split subjects")
        decisions = {d.subject: d for d in _decide(state, _votes(state))}
        return {"compromises": converge.compromises(runtime, state["split"], _ballot(state), _votes(state), decisions)}

    def r7_revote_fan_out(state: Stage0State):
        items = converge.revote_items(_ballot(state), state["compromises"])
        started("R7", proposals.voters(), "Re-voting on the compromises")
        return [Send("r7_revote", {"agent": a, "sheet": state["fact_sheet"], "items": items}) for a in proposals.voters()]

    def r7_revote(branch: dict) -> dict:
        try:
            drafts = converge.revote(branch["agent"], runtime, branch["sheet"], branch["items"])
        except AgentError as e:
            return {"r7_failures": [{"agent": branch["agent"], "error": str(e)[:500]}]}
        return {"revote_drafts": [{"agent": branch["agent"], **d.model_dump(mode="json")} for d in drafts]}

    def r7_final(state: Stage0State) -> dict:
        started("R7", ["moderator"], "Counting, and writing the position the panel signs")
        first = _votes(state)
        split = set(state.get("split", [])) if state.get("compromises") else set()
        second = []
        if split:
            items = converge.revote_items(_ballot(state), state["compromises"])
            for agent in proposals.voters():
                mine = [votes.VoteDraft.model_validate({k: v for k, v in d.items() if k != "agent"})
                        for d in state.get("revote_drafts", []) if d["agent"] == agent]
                second += votes.check_votes(agent, mine, items)[0]
            for v in second:
                bus.emit("vote.cast", "strategy", revote=True, **v.model_dump(mode="json"))
        final_votes = converge.merge_votes(first, second, split)
        decisions = _decide(state, final_votes)
        rows = converge.board(decisions, final_votes, _ballot(state), revoted=split,
                              names={i["id"]: i["name"] for i in state["shortlist"]})
        statement, guardrails, by_moderator = converge.write_statement(runtime, rows)
        for r in rows:
            r["guardrail"] = guardrails.get(r["subject"])
            bus.emit("consensus.result", "strategy", **r)
        stage = converge.overall(decisions)
        failures = state.get("r7_failures", [])
        for f in failures:
            bus.emit("error", "strategy", round="R7", **f)
        decision = {"stage": "strategy", "stage_agreement": stage, "statement": statement,
                    "statement_by": "moderator" if by_moderator else "code", "board": rows,
                    "revote": {"subjects": sorted(split), "compromises": state.get("compromises", {}),
                               "votes": [v.model_dump(mode="json") for v in second], "failures": failures}}
        bus.emit("stage.decided", "strategy", stage_agreement=stage, statement=statement,
                 outcomes={r["subject"]: r["outcome"] for r in rows})
        Path(state["run_dir"], "strategy_decision.json").write_text(json.dumps(decision, indent=2, ensure_ascii=False),
                                                                    encoding="utf-8")
        names = {**converge.LEAD_NAMES, **{i["id"]: i["name"] for i in state["shortlist"]}}
        Path(state["run_dir"], "strategy_adr.md").write_text(adr.strategy_adr(
            state["fact_sheet"]["document"], state["fact_sheet"]["facts"], decision, state.get("cards", []),
            state.get("challenges", []), names, gate=state.get("gate"),
            precedents=state.get("precedents")), encoding="utf-8")
        return {"decision": decision, "final_votes": [v.model_dump(mode="json") for v in final_votes]}

    def reviewer_gate(state: Stage0State) -> dict:
        summary = {
            "facts": len(state["fact_sheet"]["facts"]),
            "binding": [i["id"] for i in state["shortlist"] if i["status"] == "binding"],
            "candidates": [i["id"] for i in state["shortlist"] if i["status"] == "candidate"],
            "cards": {a: sum(c["agent"] == a for c in state.get("cards", [])) for a in proposals.voters()},
            "r2_failures": [f["agent"] for f in state.get("r2_failures", [])],
            "verdicts": {v: sum(c["verdict"] == v for c in state.get("checks", []))
                         for v in ("verified", "partly_supports", "unverified", "contradicted")},
            "removed_cards": [c["id"] for c in state.get("cards", []) if c.get("removed")],
            "challenges": {t: sum(c["type"] == t for c in state.get("challenges", []))
                           for t in ("fact", "relevance", "evidence", "cost", "alternative")},
            "counter_cases": [c["target_subject"] for c in state.get("challenges", []) if c["counter_case"]],
            "untested": state.get("untested", []),
            "r4_failures": [f["agent"] for f in state.get("r4_failures", [])],
            "rebuttals": {k: sum(r["response"] == k for r in state.get("rebuttals", [])) for k in ("rebut", "concede", "revise")},
            "conceded_cards": [c["id"] for c in state.get("cards", []) if c.get("conceded")],
            "challenges_open": sum(not c.get("answered") and not c["removed"] for c in state.get("challenges", [])),
            "r5_failures": [f["agent"] for f in state.get("r5_failures", [])],
            "tally": state.get("tally", {}),
            "r6_failures": [f["agent"] for f in state.get("r6_failures", [])],
            "outcomes": {r["subject"]: (r["outcome"], r["agreement"]) for r in state.get("decision", {}).get("board", [])},
            "stage_agreement": state.get("decision", {}).get("stage_agreement"),
            "statement": state.get("decision", {}).get("statement"),
            "pending_rounds": state.get("pending_rounds", []),
        }
        answer = interrupt(summary)          # pauses here until resumed with the reviewer's answer
        review = {"decision": answer.get("decision", "approve"), "reason": answer.get("reason", ""),
                  "reviewer": answer.get("reviewer", "reviewer"), "auto": bool(answer.get("auto", False))}
        bus.emit("reviewer.signed", "strategy", **review)
        Path(state["run_dir"], "review.json").write_text(json.dumps(review, indent=2), encoding="utf-8")
        doc = Path(state["run_dir"], "strategy_adr.md")
        if doc.exists():
            doc.write_text(adr.with_signoff(doc.read_text(encoding="utf-8"), review, []), encoding="utf-8")
        recorded = ledger.record_run(Path(state["run_dir"]))          # the signed record (task 1.8)
        return {"review": review, "recorded": recorded}

    g = StateGraph(Stage0State)
    g.add_node("r0_fact_sheet", r0_fact_sheet)
    g.add_node("r1_shortlist", r1_shortlist)
    g.add_node("r2_propose", r2_propose)
    g.add_node("r2_check", r2_check)
    g.add_node("r3_fact_check", r3_fact_check)
    g.add_node("r4_challenge", r4_challenge)
    g.add_node("r4_check", r4_check)
    g.add_node("r5_rebut", r5_rebut)
    g.add_node("r5_check", r5_check)
    g.add_node("r6_vote", r6_vote)
    g.add_node("r6_check", r6_check)
    g.add_node("r7_tally", r7_tally)
    g.add_node("r7_compromise", r7_compromise)
    g.add_node("r7_revote", r7_revote)
    g.add_node("r7_final", r7_final)
    g.add_node("reviewer_gate", reviewer_gate)
    g.add_edge(START, "r0_fact_sheet")
    g.add_edge("r0_fact_sheet", "r1_shortlist")
    g.add_conditional_edges("r1_shortlist", r2_fan_out, ["r2_propose"])
    g.add_edge("r2_propose", "r2_check")
    g.add_edge("r2_check", "r3_fact_check")
    g.add_conditional_edges("r3_fact_check", r4_fan_out, ["r4_challenge", "r4_check"])
    g.add_edge("r4_challenge", "r4_check")
    g.add_conditional_edges("r4_check", r5_fan_out, ["r5_rebut", "r5_check"])
    g.add_edge("r5_rebut", "r5_check")
    g.add_conditional_edges("r5_check", r6_fan_out, ["r6_vote", "r6_check"])
    g.add_edge("r6_vote", "r6_check")
    g.add_edge("r6_check", "r7_tally")
    g.add_conditional_edges("r7_tally", r7_route, ["r7_compromise", "r7_final"])
    g.add_conditional_edges("r7_compromise", r7_revote_fan_out, ["r7_revote"])
    g.add_edge("r7_revote", "r7_final")
    g.add_edge("r7_final", "reviewer_gate")
    g.add_edge("reviewer_gate", END)
    # In-memory checkpoints for Phase 1; Week 2 switches to the Postgres checkpointer so a
    # paused session survives a restart.
    return g.compile(checkpointer=checkpointer or InMemorySaver())


def start(graph, session: str, prd_path: str, run_dir: str, mode: str = "production") -> dict:
    """Run until the reviewer gate. Returns what the reviewer needs to see."""
    cfg = {"configurable": {"thread_id": session}}
    graph.invoke({"session": session, "prd_path": prd_path, "run_dir": run_dir, "mode": mode}, cfg)
    snap = graph.get_state(cfg)
    waiting = [i.value for t in snap.tasks for i in getattr(t, "interrupts", ())]
    return {"paused_at": list(snap.next), "for_reviewer": waiting[0] if waiting else None, "state": snap.values}


def resume(graph, session: str, answer: dict) -> dict:
    """Resume a paused session with the reviewer's answer; returns the final state."""
    cfg = {"configurable": {"thread_id": session}}
    graph.invoke(Command(resume=answer), cfg)
    return graph.get_state(cfg).values
