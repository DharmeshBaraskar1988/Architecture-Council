# Council replay viewer (Next.js)

Replays any run in `../data/runs`: fact sheet, shortlist, blind proposals, fact-check stamps,
challenges, rebuttals, the blind vote, the decision board and the position statement, with
evidence cards sliding in on the right as each agent speaks.

Phase 1 task 1.18. It reads the run folders from disk on the server; nothing is sent anywhere.
Phase 3 grows this into the live council room.

```powershell
cd $HOME\Documents\council\frontend
npm install          # once
npm run dev          # http://localhost:3000
```

- `/` starts a session on your uploaded PRD and lists sessions.
- `/runs/<id>/room` is the council room: seats, spoken turns, evidence on the table, raise your hand,
  and your sign-off at the end. Follows a running session live. `?turn=N` opens on turn N, `?turn=end` on the result.
- `/runs/<id>` is the board view; add `?at=end` to open on the result.
- Voices use the browser's own speech (Edge and Chrome on Windows have several English voices).
- Controls: play/pause, step, speed 1–8×, scrub, or jump to the end of any round.
- Another runs folder: set `COUNCIL_RUNS_DIR` before `npm run dev`.
- Production build: `npm run build`, then `npm start`.
