# Instructions for Claude

## When the user says "run the project" (or "run the program", "start", "where are we")

1. Read [STATUS.md](STATUS.md) first, and report to the user briefly: what is installed, what is done,
   what is pending, and the plan.
2. Check that the install still matches: `backend\.venv\Scripts\python.exe` exists, `frontend\node_modules`
   exists. If not, run `.\setup` (setup.cmd; `.ps1` scripts are blocked by the execution policy on this laptop,
   so the user runs `.\setup`, `.\council ...` and `.\start` rather than `.ps1` files or `Activate.ps1`).
3. Run the offline checks (`python -m pytest -q` in `backend\`, then `council validate`), then a live run if
   the user wants one: `council run --prd <file> --review skip` (never `--review approve` without asking: it
   writes the decision database).
4. At the end of the session, update STATUS.md (installed versions, done, current state, pending, plan, date).

## Constraints

- No Docker in Phase 1: the decision database is SQLite (`data\council.db`).
- Another session works in `avatar\` and the room UI; leave those files alone unless asked.
- Never commit `.env`, `data\uploads\`, `data\sources\` or avatar model weights.
- Task detail and acceptance criteria live in [PROGRESS.md](PROGRESS.md).
