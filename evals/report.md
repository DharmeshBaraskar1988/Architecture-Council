# Phase 1 evals report

Generated 24 Oct 2026 23:19 by `council evals` from the run folders listed below. Every number is read from the run's own files.

## Acceptance by sample

| Criterion | S1 | S2 | S3 |
|---|---|---|---|
| Fact quotes pass the exact-quote check (≥ 90%) | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| Key facts as expected | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| Binding frameworks found | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| Shortlist matches the golden result | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| Run reached a decision | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| Every open framework challenged | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| A verdict on every citation | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| V, E, A and an outcome by the rules | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| No unverified or invented citation weighted | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| Position statement and ADR | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| Decision record saved after sign-off | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| Build approach, delivery path, swap plan for every POC part | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| Under 5 minutes; cost measured | ❌ 2/3 | ✅ 3/3 | ✅ 3/3 |
| Stable outcome on binding and clear subjects | ❌ | ❌ | ❌ |

Production gate over the whole catalog: ❌ 55 candidates, 2 no native service, 17 poc only, 36 production eligible; without evidence links: openai_moderation, openai_embeddings, openai_api.

## S1 · s1_financial_briefing.md

| Run | Quotes | Time | Cost | Calls (failed) | Stage agreement | Problems |
|---|---|---|---|---|---|---|
| 20261024-230519-15fc | 100% | 238 s | $0.326 | 40 (10) | 63.6% | none |
| 20261024-230917-0f76 | 100% | 271 s | $0.248 | 40 (10) | 67.9% | none |
| 20261024-231348-c549 | 100% | 315 s | $0.254 | 43 (12) | 62.9% | Under 5 minutes; cost measured: {"seconds": 315, "cost_usd": 0.254, "calls": 43, "failed_calls": 12} |

Outcome per subject and run (agreement %):

| Subject | run 1 | run 2 | run 3 |
|---|---|---|---|
| adr | reviewer decides 55 | selected 84 | reviewer decides 47 |
| atam | rejected 25 | reviewer decides 58 | rejected 35 |
| azure_waf | selected 78 | reviewer decides 54 | reviewer decides 74 |
| build_approach | reviewer decides 40 | selected with condition 73 | selected with condition 70 |
| c4_model | reviewer decides 56 | reviewer decides 55 | reviewer decides 51 |
| delivery_path | selected with condition 70 | reviewer decides 50 | reviewer decides 50 |
| dpdp_india | selected 100 | selected 100 | selected 100 |
| event_driven | reviewer decides 53 | reviewer decides 50 | reviewer decides 48 |
| evolutionary_architecture | selected 88 | selected 80 | selected 85 |
| microservices_first | parked | parked | parked |
| twelve_factor | selected with condition 72 | selected 75 | selected with condition 68 |

Stability: UNSTABLE: adr: reviewer_decides 55.0 / selected 84.4 / reviewer_decides 47.1; atam: rejected 25.0 / reviewer_decides 58.0 / rejected 35.1; azure_waf: selected 77.8 / reviewer_decides 54.0 / reviewer_decides 74.5; twelve_factor: selected_with_condition 72.1 / selected 75.0 / selected_with_condition 68.5

## S2 · s2_shopsphere.md

| Run | Quotes | Time | Cost | Calls (failed) | Stage agreement | Problems |
|---|---|---|---|---|---|---|
| 20261024-223717-6949 | 100% | 279 s | $0.299 | 40 (10) | 68.9% | none |
| 20261024-224200-3598 | 100% | 233 s | $0.224 | 40 (10) | 70.7% | none |
| 20261024-224554-4450 | 100% | 229 s | $0.211 | 39 (11) | 70.6% | none |

Outcome per subject and run (agreement %):

| Subject | run 1 | run 2 | run 3 |
|---|---|---|---|
| adr | selected with condition 60 | reviewer decides 74 | selected 87 |
| atam | rejected 36 | rejected 28 | reviewer decides 46 |
| azure_waf | reviewer decides 46 | reviewer decides 78 | reviewer decides 71 |
| build_approach | selected 80 | selected 84 | selected with condition 73 |
| c4_model | reviewer decides 53 | selected 78 | selected 85 |
| delivery_path | selected with condition 70 | reviewer decides 50 | reviewer decides 43 |
| dpdp_india | selected 100 | selected 100 | selected 100 |
| evolutionary_architecture | selected 87 | reviewer decides 60 | selected with condition 60 |
| owasp_asvs | reviewer decides 73 | selected with condition 65 | selected with condition 63 |
| pci_dss | selected 100 | selected 100 | selected 100 |
| twelve_factor | reviewer decides 53 | selected with condition 62 | reviewer decides 48 |

Stability: UNSTABLE: adr: selected_with_condition 60.4 / reviewer_decides 73.5 / selected 86.7; atam: rejected 35.5 / rejected 28.0 / reviewer_decides 46.0; build_approach: selected 80.0 / selected 84.0 / selected_with_condition 73.3; c4_model: reviewer_decides 52.9 / selected 77.5 / selected 85.3; evolutionary_architecture: selected 86.7 / reviewer_decides 60.0 / selected_with_condition 60.0

## S3 · s3_movewell_clinics.docx

| Run | Quotes | Time | Cost | Calls (failed) | Stage agreement | Problems |
|---|---|---|---|---|---|---|
| 20261024-224943-e6da | 100% | 291 s | $0.374 | 41 (10) | 67.6% | none |
| 20261024-225435-4100 | 100% | 295 s | $0.397 | 42 (10) | 65.7% | none |
| 20261024-225930-6f57 | 100% | 281 s | $0.275 | 41 (10) | 71.9% | none |

Outcome per subject and run (agreement %):

| Subject | run 1 | run 2 | run 3 |
|---|---|---|---|
| adr | selected 83 | reviewer decides 57 | selected with condition 65 |
| atam | rejected 13 | reviewer decides 43 | selected with condition 60 |
| aws_waf | selected with condition 61 | reviewer decides 48 | selected with condition 67 |
| build_approach | selected 80 | reviewer decides 43 | selected with condition 73 |
| c4_model | selected with condition 70 | reviewer decides 56 | selected with condition 61 |
| delivery_path | rejected 30 | selected with condition 70 | selected with condition 67 |
| dpdp_india | selected 100 | selected 100 | selected 100 |
| event_driven | reviewer decides 56 | reviewer decides 52 | reviewer decides 51 |
| evolutionary_architecture | selected 79 | reviewer decides 85 | reviewer decides 82 |
| gdpr | selected 100 | selected 100 | selected 100 |
| owasp_asvs | reviewer decides 55 | reviewer decides 51 | reviewer decides 50 |
| pci_dss | selected 100 | selected 100 | selected 100 |
| twelve_factor | reviewer decides 53 | reviewer decides 49 | reviewer decides 59 |

Stability: UNSTABLE: adr: selected 83.3 / reviewer_decides 56.7 / selected_with_condition 64.9; atam: rejected 13.3 / reviewer_decides 43.2 / selected_with_condition 60.0; build_approach: selected 80.0 / reviewer_decides 43.3 / selected_with_condition 73.3; delivery_path: rejected 30.0 / selected_with_condition 70.0 / selected_with_condition 67.0; evolutionary_architecture: selected 78.7 / reviewer_decides 85.0 / reviewer_decides 81.8
