"""R0 · Fact sheet. The Moderator extracts facts; code checks every quote against the PRD.

A fact is `confirmed` only if its quote is found in the document. The model cannot mark
anything confirmed by itself. Facts the model says are not stated become `assumed`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from app.agents.runtime import AgentRuntime
from app.config import config
from app.events.bus import EventBus
from app.factcheck.quotes import find_quote
from app.knowledge.ingest import Document
from app.schemas import Fact, FactSheet, FactStatus

PROMPT = (Path(__file__).resolve().parents[1] / "agents" / "prompts" / "moderator_factsheet.md")


class RawFact(BaseModel):
    key: str
    value: Any
    quote: Optional[str] = None
    page: Optional[int] = None
    stated: bool = True           # False = the model infers it; it becomes an assumption
    note: Optional[str] = None


def _coerce(value: Any, spec: dict) -> Any:
    t = spec.get("type")
    if t == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "y", "1")
        return bool(value)
    if t == "int":
        try:
            return int(str(value).replace(",", "").split()[0])
        except (ValueError, IndexError):
            return value
    if t == "enum":
        v = str(value).strip().lower()
        return v if v in spec.get("values", []) else value
    return value


def _doc_for_prompt(doc: Document, max_chars: int = 60000) -> str:
    out, used = [], 0
    for p in doc.pages:
        block = f"\n=== PAGE {p.number} ===\n{p.text}\n"
        if used + len(block) > max_chars:
            out.append("\n=== (document truncated for length) ===\n")
            break
        out.append(block)
        used += len(block)
    return "".join(out)


def build_fact_sheet(doc: Document, runtime: AgentRuntime, bus: Optional[EventBus] = None) -> FactSheet:
    vocab: dict = config("fact_vocabulary")["facts"]
    vocab_lines = "\n".join(f"- {k} ({v['type']}{': ' + ', '.join(v['values']) if v.get('values') else ''})"
                            f"{' — ' + v['help'] if v.get('help') else ''}" for k, v in vocab.items())
    system = PROMPT.read_text(encoding="utf-8").replace("{{VOCABULARY}}", vocab_lines)
    raw: list[RawFact] = runtime.ask("moderator", system, _doc_for_prompt(doc), list[RawFact])

    sheet = FactSheet(document=doc.name)
    seen: set[str] = set()
    for r in raw:
        if r.key not in vocab or r.key in seen:
            continue                                   # unknown or duplicate keys are dropped
        seen.add(r.key)
        fact = Fact(id=f"F-{len(sheet.facts) + 1:02d}", key=r.key, value=_coerce(r.value, vocab[r.key]),
                    quote=r.quote, page=r.page, note=r.note)
        if not r.stated or not r.quote:
            fact.status, fact.quote, fact.page = FactStatus.assumed, None, None
            fact.note = fact.note or "Not stated in the PRD"
        else:
            q = find_quote(doc, r.quote, r.page)
            words = vocab[r.key].get("quote_must_mention")
            if q.found and words and not any(w in r.quote.lower() for w in words):
                # The quote exists but does not state this fact: keep it as an assumption the reviewer sees.
                fact.status, fact.quote, fact.page = FactStatus.assumed, None, None
                fact.note = (f"Read from “{r.quote}”, which does not mention {' / '.join(words)}: "
                             "treated as an assumption")
            elif q.found:
                fact.status = FactStatus.confirmed
                if not q.page_matches_claim:
                    fact.note = f"Page corrected from {r.page} to {q.page}"
                    fact.page = q.page
            else:
                fact.status = FactStatus.unverified
                fact.note = "Quote not found in the document"
        sheet.facts.append(fact)
        if bus:
            bus.emit("fact.extracted", "strategy", **fact.model_dump(mode="json"))
    if bus:
        counts = {s.value: sum(f.status == s for f in sheet.facts) for s in FactStatus}
        bus.emit("factsheet.ready", "strategy", document=doc.name, counts=counts)
    return sheet
