import pytest

from app.events.bus import EventBus, replay


def test_emit_and_replay(tmp_path):
    log = tmp_path / "debate_log.jsonl"
    bus = EventBus("s1", log)
    seen = []
    bus.subscribe(seen.append)
    bus.emit("session.started", "strategy", document="x")
    bus.emit("fact.extracted", "strategy", id="F-01")
    evs = replay(log)
    assert [e.seq for e in evs] == [1, 2] and evs[1].payload["id"] == "F-01" and len(seen) == 2


def test_unknown_event_type_rejected():
    with pytest.raises(ValueError):
        EventBus("s").emit("made.up", "strategy")
