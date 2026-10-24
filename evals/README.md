# Evals (task 1.19)

`council evals` checks every Phase 1 acceptance criterion on real runs and writes `report.md`
(and `report.json` with every number behind it).

```powershell
council evals --runs 3                 # S1, S2, S3 three times each, live (about 10 min and $0.40 per run on free tiers)
council evals --runs 1 --samples s3    # one sample
council evals --from 20261024-133706-4e91 20261024-140112-a1b2   # report on runs that already exist
```

Samples are in `data/samples/prds/` and their golden expectations in `backend/tests/fixtures/s*_expected.yaml`:
which facts must be confirmed and with which values, and the expected shortlist (binding, candidate,
not applicable). Golden runs are auto-approved into `data/evals/council_evals.db`, never the real
decision database, so test runs do not become precedents.

What is checked, per run, from the run's own files:

| Criterion | From |
|---|---|
| Fact quotes pass the exact-quote check (≥ 90%) | `fact_sheet.json` |
| Key facts as expected; binding frameworks found; shortlist matches | `fact_sheet.json`, `applicability.json` |
| Every open framework challenged | `challenges.json` |
| A verdict on every citation | `proposals.json`, `factcheck.json` |
| V, E, A and an outcome by the rules | `strategy_decision.json` |
| No unverified or contradicted citation carries weight | fact checks of R3, R4, R5 |
| Position statement and ADR; decision record saved after sign-off | `strategy_adr.md`, decision database |
| Build approach, delivery path, and a swap plan for every POC-only part | `strategy_decision.json`, `swap_plans.json` |
| Under 5 minutes; cost measured | `debate_log.jsonl`, `usage.json` |

Across runs of one sample: every subject that was binding or clear (agreement ≥ 75% or < 40%) in
any run must get the same outcome in every run. Over the whole catalog: every candidate has a final
gate verdict with evidence links, and nothing preview, non-commercial or without an official API is
production-eligible.
