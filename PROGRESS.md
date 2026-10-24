# Phase 1 progress report

**Updated:** 24 Oct 2026 · **Session 2: Stage 0 completed without Docker** · **Tests:** 110 passing (backend, mock model, no network)

## Summary

| | Count |
|---|---|
| Phase 1 tasks done | 17 of 19 |
| Partly done | 2 of 19 (1.1 Docker not run, by choice; 1.19 stability not yet met) |
| Not started | 0 |

Stage 0 runs end to end on all three sample PRDs: fact sheet, shortlist, gate with live evidence,
blind proposals, fact check against crawled official pages, challenges, rebuttals (or revisions),
blind vote, consensus, ADR, sign-off, and the signed record saved to the decision database.
`evals/report.md` checks every acceptance criterion on 3 golden runs per sample.

**Without Docker** (your instruction): the decision database runs on SQLite (`data/council.db`,
same columns as `infra/db/init.sql`). PostgreSQL, pgvector embeddings and Postgres checkpoints wait
for the database server.

## Acceptance criteria (golden runs, `evals/report.md`)

| Criterion | Result |
|---|---|
| Fact sheet: ≥ 90% of facts pass the exact-quote check | ✅ 100% on every run of S1, S2, S3 |
| Binding frameworks found (PCI DSS for cards; DPDP; GDPR) | ✅ 9 of 9 runs |
| Every framework challenged; a verdict on every citation; V, E, A and outcome by the rules | ✅ 9 of 9 |
| Zero unverified or invented citations weighted | ✅ 9 of 9 |
| One statement and ADR per run; decision record saved after sign-off | ✅ 9 of 9 |
| Every catalog candidate has a gate result; nothing preview, non-commercial or unofficial production-eligible | ✅ 55 candidates, all final. ⚠️ 3 OpenAI candidates have no evidence links: openai.com refuses automated clients (save the pages once: `council crawl --manual`) |
| Build approach and delivery path named; swap plan for every POC-only part | ✅ 9 of 9 |
| Under 5 minutes; cost measured | ⚠️ 8 of 9 runs under 5 min (228–315 s), $0.21–0.40 per run, but only once Gemini's free daily quota ran out and Kabir fell back to OpenAI. On the free Gemini tier Kabir's calls queue for 2–4 minutes each, so runs take 10–16 min |
| Stability: same PRD 3 times gives the same outcome on binding or clear subjects | ❌ Binding subjects are identical in every run; non-binding frameworks swing between runs (see below) |
| Shortlist matches the golden result | ✅ 9 of 9. In S1 the model still reads "jobs run in the background" as a scaling need; that fact is now an assumption (its quote does not mention scaling), so microservices is parked for the reviewer in all three runs instead of being debated as fact |

### Why outcomes are not yet stable, and what would fix it

Binding outcomes (DPDP, PCI DSS, GDPR) never move: code decides them. Everything else moves because
the votes and the evidence weights differ from run to run (temperature 0.2, four models, different
challengers). In the golden runs Kabir was also on Gemini in some runs and on OpenAI in others
(free quota), which changes the panel itself. Options, in the order I would try them:

1. Paid keys: Gemini (Kabir stays on one model) and Anthropic (Tara and Mira on Claude, as planned).
   Today three of four voters can end up on OpenAI.
2. Temperature 0 and a fixed seed where the provider supports one.
3. Decide D-03 (a conditional vote counts 0.5): most swings are subjects near the 60/75% thresholds
   where unanimous "adopt with condition" lands on reviewer decides.
4. If still unstable: run R6 votes twice and use the median (doubles vote cost, about +$0.05 a run).

## Tasks

Legend: ✅ done · 🟡 partly done · ⬜ not started

| # | Task | Status | What exists | What is missing |
|---|---|---|---|---|
| 1.1 | Repository, Docker Compose, config skeleton, CI | 🟡 | Everything except running Docker; git repository pushed to GitHub | `docker compose up` (not run, by choice) |
| 1.2 | Agent runtime | ✅ | LiteLLM, schema validation, retries, fallbacks, cost per call; models without a key are skipped; Langfuse logging when `LANGFUSE_*` keys are set (`pip install -e ".[observability]"`) | Langfuse keys (empty in `.env`) |
| 1.3 | PRD ingestion | ✅ | Markdown, HTML, PDF (pypdf), Word with tables in place and sections split by heading | Embeddings wait for pgvector (Docker) |
| 1.4 | Fact sheet extractor | ✅ | Exact-quote check; prompt: one limiting sentence states both sides ("users are in India" → not in the EU); a fact whose quote does not mention it (`quote_must_mention` in `fact_vocabulary.yaml`) becomes an assumption | — |
| 1.5 | Event schema and log | ✅ | 13 event types, replay | — |
| 1.6 | Framework catalog | ✅ | 14 frameworks; every source on the allowlist | — |
| 1.7 | Crawler | ✅ | `knowledge/crawler.py`, `council crawl`: allowlist, robots.txt, rate limit, redirects kept on the allowlist, stored text with URL and fetch date, stale after 90 days, `--manual` capture for sites that block automated clients. 136 pages stored | Pages that refuse automated clients: OpenAI (3), MeitY (DPDP), EUR-Lex (GDPR; the European Commission page is stored instead) |
| 1.8 | Decision database | ✅ | `ledger/store.py` (SQLite): signed runs saved per subject, precedent search with context % (code), 6 clearly marked SAMPLE precedents that never carry weight; a document never cites its own earlier runs | PostgreSQL when Docker runs |
| 1.9 | Solution catalog | ✅ | 10 capabilities, 55 candidates on Azure, AWS, GCP, SaaS and open source, each with official, pricing, terms and SLA pages | Region availability per candidate (recorded only as notes) |
| 1.10 | Production gate | ✅ | `catalog/verify.py`, `council verify`: every page fetched; licence, archive state and last push from GitHub; model licences from Hugging Face; OpenSSF score; preview read from the official page. Verdicts: 36 production-eligible, 17 POC only, 2 no native service | — |
| 1.11 | Strategist agent | ✅ | Shortlist by rule, cards with crawled sources, precedents, swap plans and run mode (`--mode production/poc`) in the brief | — |
| 1.12 | Panel personas | ✅ | Four voters on different providers when all keys are set | Anthropic key (Tara on OpenAI meanwhile) |
| 1.13 | Existing-stack input | ✅ | Each owned item becomes a production-eligible reuse option in its capabilities; swap plans prefer it | Your company's list in `config/policies/existing_stack.yaml` |
| 1.14 | Debate engine | ✅ | R0–R7 in LangGraph; R5 "revise" for build approach and delivery path, so the strategy always names both | Optional second challenge cycle |
| 1.15 | Fact checker | ✅ | Vera judges claims against the best-matching passage of the crawled page; recency (stale pages never count); precedents judged by code and weighted by context match | — |
| 1.16 | Consensus engine | ✅ | V, E, A, outcomes, overrides, re-vote | D-03 decision |
| 1.17 | Outputs | ✅ | Decision board, statement, ADR with solution gate, swap plans and precedents, decision record | — |
| 1.18 | Replay viewer and reviewer gate | ✅ | Next.js viewer and council room; sign-off in the room now also writes the decision database | — |
| 1.19 | Golden runs and evals | 🟡 | S1, S2, S3 (messy Word PRD); `council evals`; `evals/report.md` | Stability criterion (see above) |

## Changes and decisions this session

| Change | Reason |
|---|---|
| Crawler on httpx and a standard-library HTML reader, not Crawl4AI | Official docs pages need no headless browser; Crawl4AI needs Playwright. Pages that need JavaScript are reported as failed, never stored as evidence |
| Robots.txt and bot blocks are respected, never worked around | CloudAMQP removed from the catalog (its legal pages disallow crawlers); OpenAI, MeitY and EUR-Lex need a manual save |
| Gate: an SLA only in an enterprise contract makes a service POC-only | OpenAI, Anthropic, ElevenLabs, HeyGen, Pinecone, Neon and Vercel publish no standard SLA; the swap plan names the production-eligible alternative |
| Licence policy accepts GitHub's old SPDX ids (AGPL-3.0, GPL-3.0, …) and lists Llama licences as review needed | The GitHub licence API still returns the old ids |
| MuseTalk and Kokoro are POC-only: no push in 12 months | Rule: maintained = not archived and pushed within a year |
| Decision database on SQLite | No Docker (your instruction); same columns as the PostgreSQL schema |
| A run never cites the same document's earlier runs as precedents | Circular, and it would make golden runs depend on each other |
| Golden runs are signed into `data/evals/council_evals.db`, not the real database | Test runs must not become precedents |
| R5 "revise" for the two lead subjects | In the first S3 run Tara conceded her only build-approach card and the strategy named none |
| Word documents: tables in place, sections by heading | All tables used to land at the end, in one section |
| Kabir stays on `gemini-3.7-flash` | Tested `gemini-3.5-flash-lite` on the S3 brief: 21 s instead of 2–3 min, but generic cards that adopt everything |

## Open items for you

1. **Keys:** a paid Gemini key and an Anthropic key fix the run time and keep four providers (see Stability).
2. **Manual saves:** open these in your browser, save the page, then `council crawl --manual URL FILE`:
   `https://openai.com/api/`, `https://openai.com/api/pricing/`, `https://openai.com/policies/services-agreement/`,
   `https://www.meity.gov.in/data-protection-framework`, `https://eur-lex.europa.eu/eli/reg/2016/679/oj`.
3. **D-03:** how much a conditional vote counts (now 0.5).
4. Your company's existing tools (`config/policies/existing_stack.yaml`) and must-follow rules (`config/policies/org_policy.yaml`).
5. A real PRD to replace or join S3 (S3 is a realistic but fictional Word document).
6. Langfuse keys, if you want every prompt and cost in Langfuse.

## Next session

1. Stability: temperature 0, then D-03, then median of two votes if needed; rerun `council evals`.
2. Docker when allowed: PostgreSQL + pgvector, Postgres checkpoints, embeddings for document chunks.
3. Phase 2: Stage 1 (requirements) on the same engines.
