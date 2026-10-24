# Replay viewer (task 1.18)

The viewer is the Next.js app in `frontend/` (chosen instead of plain HTML). It replays any run's
`debate_log.jsonl`, and the council room (`/runs/<id>/room`) holds the reviewer gate: approve, or
override with a reason. Signing writes `review.json`, a `reviewer.signed` event, the signed ADR, and
the decisions to the decision database (`council ledger record`).

```powershell
cd frontend; npm install; npm run dev     # then http://localhost:3000, or: council view <run id>
```
