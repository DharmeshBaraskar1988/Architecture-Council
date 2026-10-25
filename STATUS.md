# Project status: AI Architecture Council

**Last updated:** 25 Oct 2026, 15:00 IST · **Phase:** 1 (Stage 0, Strategy) · **Branch:** `main`, pushed to
https://github.com/DharmeshBaraskar1988/Architecture-Council

Read this first. For the full task-by-task table and acceptance criteria, see [PROGRESS.md](PROGRESS.md).
Update this file at the end of every session.

---

## 1. Installed on this laptop

| Item | Version | Where | Check |
|---|---|---|---|
| Python | 3.12.10 in the venv; `py -3` launcher finds 3.14 | system | `python --version` |
| Node.js / npm | 24.19.0 / 11.17.0 | system | `node --version` |
| Backend virtual environment | — | `backend\.venv` | `backend\.venv\Scripts\python.exe` exists |
| `council` package (editable) | 0.1.0 | `backend\.venv` | `backend\.venv\Scripts\council.exe` exists |
| litellm | 1.106.2 | venv | `pip list` in the venv |
| langgraph | 1.2.17 | venv | |
| pydantic | 2.14.1 | venv | |
| httpx | 0.28.1 | venv | |
| pypdf / python-docx | 6.21.2 / 1.2.0 | venv | |
| edge-tts | 7.3.1 | venv | |
| PyYAML / pytest | 6.0.3 / 9.1.1 | venv | |
| langfuse (optional) | **not installed** | — | `pip install -e ".[observability]"` |
| Frontend packages | next 16.4.3, react 19.3.1, typescript 5.9.3 | `frontend\node_modules` | `npm ls --depth=0` in `frontend` |
| Docker / PostgreSQL | **not used** (by choice) | — | Phase 1 uses SQLite `data\council.db` |
| VS Code, CI and Makefile copies | **not copied yet** | `setup\` | `.vscode\`, `.github\workflows\`, `Makefile` missing |

**API keys set in `.env`** (names only): OpenAI, Gemini, Groq, Ollama. **Not set:** Anthropic, Langfuse, GitHub token.
`COUNCIL_MOCK_LLM=0` (real model calls).

**Data on disk:** catalog verification in `data\catalog\`, crawled pages in `data\sources\`, decision database
`data\council.db`, run folders in `data\runs\`.

## 2. Done

| When | What |
|---|---|
| Session 1 (24 Oct) | Repository, config, catalogs (14 frameworks, 55 solution candidates), agent runtime, PRD ingestion, fact sheet, event log, debate engine R0–R7 in LangGraph, fact checker, consensus engine, outputs (ADR, statement), Next.js viewer and council room |
| Session 2 (24 Oct) | Crawler (136 pages), live production gate, decision database on SQLite, golden evals on S1–S3 (`evals\report.md`); committed `4a42eb0` and pushed |
| Session 3 (25 Oct) | Checked the install: **110 tests pass**, `council validate` passes. Wrote [setup.ps1](setup.ps1) and tested it end to end (`-SkipEditorFiles`). Removed a stale `~ouncil` pip leftover from the venv. Live S1 run `20261025-145400-201b` completed (see section 3). Added STATUS.md and CLAUDE.md. Found scripts blocked (execution policy Restricted); added `setup.cmd`, `council.cmd`, `start.cmd` launchers and tested them. Viewer serves the run and room pages (HTTP 200) |

Phase 1 tasks: **17 of 19 done**, 2 partly done (1.1 Docker not run by choice; 1.19 stability not met).

## 3. Current state

- **Last live run:** `data\runs\20261025-145400-201b` (S1 financial briefing, `--review skip`): **completed**,
  about 4 min, 25 model calls, 0 failed, **$0.39**. Stage agreement **69.7%**.
  Selected: Azure WAF, Twelve-Factor, DPDP India (binding). With condition: event-driven (async/background only),
  build approach, delivery path. Reviewer decides: ADR, evolutionary architecture. Rejected: ATAM, C4.
  Parked: microservices-first (depends on an assumed fact). **Not signed**: waits for sign-off in the council room.
- **Git:** everything committed and pushed; working tree clean. `a54547b` setup files, launchers, STATUS.md and
  CLAUDE.md; `b63578c` the avatar session's change (room shows still 3D portraits; MuseTalk talking clips removed).
  The avatar work belongs to a **separate session**; leave `avatar\` and the room UI alone unless asked.
- **Loose end:** `avatar\portraits\options\` is now in `.gitignore` but its 25 PNGs are still tracked in git
  (`git rm -r --cached avatar/portraits/options` would untrack them, keeping the files on disk).

## 4. Pending (needs you)

1. **Keys:** a paid Gemini key and an Anthropic key. They fix the run time (free Gemini makes runs 10–16 min)
   and keep four providers on the panel.
2. **Manual page saves** (sites block automated clients): save each page in your browser, then
   `council crawl --manual URL FILE` for: `https://openai.com/api/`, `https://openai.com/api/pricing/`,
   `https://openai.com/policies/services-agreement/`, `https://www.meity.gov.in/data-protection-framework`,
   `https://eur-lex.europa.eu/eli/reg/2016/679/oj`.
3. **Decision D-03:** how much a conditional vote counts (now 0.5).
4. Your company's tools in `config\policies\existing_stack.yaml` and rules in `config\policies\org_policy.yaml`.
5. A real PRD to join or replace S3.
6. Optional: Langfuse keys; copy the editor files (`.\setup.ps1` does it).
7. Sign off run `20261025-145400-201b` in the council room, or leave it.

## 5. Plan (next work)

1. **Stability (task 1.19):** temperature 0 and a fixed seed, then D-03, then the median of two votes if needed;
   rerun `council evals`.
2. **Docker, when allowed:** PostgreSQL + pgvector, Postgres checkpoints, embeddings for document chunks.
3. **Phase 2:** Stage 1 (requirements) on the same engines.

## 6. How to run

PowerShell scripts are **blocked on this laptop** (execution policy not set = Restricted), so `.\setup.ps1` and
`Activate.ps1` fail when typed directly. Use the `.cmd` launchers in the `council` folder instead; they work in
PowerShell and cmd and need no venv activation:

```powershell
cd $HOME\Documents\council
.\setup                              # setup.cmd: install/repair everything, run tests (safe to repeat)
.\council validate                   # council.cmd: any council command
.\council run --prd data\samples\prds\s1_financial_briefing.md --review skip
.\start                              # start.cmd: viewer + council room in a new window, opens http://localhost:3000
```

Optional, to allow `.ps1` scripts for good: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
