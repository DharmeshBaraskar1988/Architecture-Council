# AI Architecture Council

A council of AI agents on different model providers, orchestrated with LangGraph, debates a project's architecture from the
facts in its product document, gets every claim fact-checked, votes, and reaches one agreed
position with an agreement percentage. A human reviewer signs off, and the signed decision becomes
a precedent for later sessions.

This repository is **Phase 1: the Strategy stage (Stage 0)**. Status of every task and file: [PROGRESS.md](PROGRESS.md).

## Set up on Windows (PowerShell)

```powershell
cd $HOME\Documents\council\backend
python -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -e ".[dev]"
python -m pytest -q                 # tests, no API keys and no network needed
```

macOS or Linux: same steps with `source .venv/bin/activate`.

Then, once, move the VS Code and CI files into place (see [setup/README.md](setup/README.md)):

```powershell
cd $HOME\Documents\council
New-Item -ItemType Directory -Force .vscode, .github\workflows | Out-Null
Copy-Item setup\vscode\*.json .vscode\
Copy-Item setup\github\tests.yml.txt .github\workflows\tests.yml
Copy-Item setup\Makefile.txt Makefile
```

## First run

1. Copy `.env.example` to `.env` and add keys for at least two providers.
2. Check the model names in `config/personas.yaml` against each provider's current model list.
3. Fetch the evidence and check the catalog (a few minutes, no model calls):

```powershell
council crawl            # every framework and solution page on the allowlist, into data/sources/
council verify           # production gate with live evidence: pages, GitHub, Hugging Face, OpenSSF
council ledger seed      # optional: load the clearly marked SAMPLE precedents
```

4. Run the council:

```powershell
council run --prd data\samples\prds\s1_financial_briefing.md
council view             # the latest run in the replay viewer and council room
```

Each run writes a folder in `data/runs/<id>/`: `fact_sheet.json`, `applicability.json`,
`solution_gate.json`, `swap_plans.json`, `precedents.json`, `proposals.json`, `factcheck.json`,
`challenges.json`, `rebuttals.json`, `votes.json`, `strategy_decision.json`, `strategy_adr.md`,
`debate_log.jsonl` and `usage.json` (tokens and cost per call).

## Commands

| Command | What it does | Needs keys |
|---|---|---|
| `council validate` | Checks every framework and solution catalog file, and that every link is on the allowlist | No |
| `council crawl [--refresh]` | Fetches every catalog source page (allowlist, robots.txt, rate limit) with its fetch date | No |
| `council crawl --manual URL FILE` | Stores a page you saved from your browser, for official sites that block automated clients | No |
| `council verify [--refresh]` | Live gate verifier, then the gate report for every candidate | No |
| `council gate [--out FILE]` | Gate report from the last verification | No |
| `council run --prd FILE` | Stage 0, R0 to R7, then the reviewer gate. `--review ask/approve/skip`, `--mode production/poc` | Yes |
| `council ledger seed/list/search/record [--run ID]` | The decision database: samples, list, precedents for a run, save a signed run | No |
| `council evals [--runs 3] [--from ID ...]` | Golden runs on S1–S3 and the acceptance report `evals/report.md` | Yes (runs) |
| `council view [ID]` | Opens a run in the viewer (start it first: `npm run dev` in `frontend/`) | No |

`--review ask` (default) asks you in the terminal, `approve` signs automatically, `skip` leaves the
session paused for you to sign in the council room.

## Where things are

| Folder | What |
|---|---|
| `docs/` | The build plan console and the council room demo (open in a browser) |
| `frontend/` | Next.js replay viewer and council room: `npm install`, `npm run dev`, open http://localhost:3000 |
| `config/` | Everything people tune: agents, thresholds, evidence weights, licence policy, crawl allowlist, frameworks, solutions |
| `backend/app/` | The code, one folder per responsibility; `orchestrator/graph.py` is the LangGraph flow |
| `backend/tests/` | Tests (mock model, no network); `tests/fixtures/` holds the golden expectations |
| `data/samples/prds/` | Sample PRDs S1, S2 (Markdown) and S3 (a messy Word document); all fictional |
| `data/precedents/` | SAMPLE precedents (invented, never weighted) |
| `data/runs/`, `data/sources/`, `data/catalog/`, `data/council.db` | Local output: runs, crawled pages, verification, decision database (not committed) |
| `evals/` | `council evals` report |
| `infra/db/init.sql` | PostgreSQL + pgvector schema for when the database server runs (Docker) |

## Database

Phase 1 runs without Docker: the decision database is SQLite (`data/council.db`) with the same
`decisions` columns as `infra/db/init.sql`. Moving to PostgreSQL later (`docker compose up -d`) is a
change of connection, not of data.
