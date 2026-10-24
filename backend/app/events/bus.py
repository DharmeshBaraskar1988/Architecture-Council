"""Event stream. Every step of a session is an event; the log replays the whole debate.

The replay viewer (Phase 1, Week 4) renders these events as the cinematic pop-ups.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

EVENT_TYPES = {
    "session.started", "fact.extracted", "factsheet.ready", "shortlist.ready",
    "card.proposed", "factcheck.verdict", "challenge.raised", "rebuttal.made",
    "vote.cast", "consensus.result", "stage.decided", "reviewer.signed", "error",
    "round.started",          # who is working now: the room shows them thinking
    "agent.introduced",       # who sits at the table: role, specialty, rounds, LLM
}


class Event(BaseModel):
    seq: int
    type: str
    session: str
    stage: str
    payload: dict[str, Any] = Field(default_factory=dict)
    at: str


class EventBus:
    def __init__(self, session: str, log_path: Optional[Path] = None):
        self.session = session
        self.log_path = log_path
        self._seq = 0
        self._subs: list[Callable[[Event], None]] = []
        self.events: list[Event] = []
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("", encoding="utf-8")

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        self._subs.append(fn)

    def emit(self, type: str, stage: str, **payload: Any) -> Event:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type '{type}'")
        self._seq += 1
        ev = Event(seq=self._seq, type=type, session=self.session, stage=stage, payload=payload,
                   at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.events.append(ev)
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(ev.model_dump_json() + "\n")
        for fn in self._subs:
            fn(ev)
        return ev


def replay(log_path: Path) -> list[Event]:
    """Read a debate_log.jsonl back into events, in order."""
    out = []
    with open(log_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(Event.model_validate(json.loads(line)))
    return sorted(out, key=lambda e: e.seq)
