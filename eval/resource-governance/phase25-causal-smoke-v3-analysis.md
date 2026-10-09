# Phase 2.5 FutureOperation lifecycle / Search Agent calibration

Governor remains shadow-only. Phase 3 = NO_GO. Absolute 80K cap remains observational. DeepSeek tokenizer PRIMARY remains 0. Full 67×2 was not run.

## Changes

- Added PLANNED / RESERVED / STARTED / COMPLETED / CANCELLED / SUPERSEDED lifecycle and terminal-node invariant. Only PLANNED nodes contribute to future buckets.
- QueryProcessor placeholders are superseded after the concrete mode becomes known.
- Removed unconditional Main planning predictions after tools. Continuation predictions carry a reason.
- Every material revision recomputes budget and records old/new budget, projected cost and explanation when unchanged. Full unchanged-reason enum is defined; inactive floors/caps are not fabricated.
- Added lifecycle events and per-need product retrieval attribution.
- Targeted collection exposed tool-name set deduplication losing parallel call cardinality. Predictor now preserves parallel dispatch/product call counts.
- Search tool-result batches predict one protocol continuation; a Search Final cancels one unused continuation placeholder.

## First collection: 14 targeted requests

All 14 requests succeeded; all 14 traces were downloaded and eligible for replay. Accounting errors = 0. No future execution facts are fed into predictions.

| Same-execution checkpoint metric | Revision 0 | First informed revision |
|---|---:|---:|
| Request MAE | 164,713 | 152,514 |
| Request MAPE | 70.00% | 58.65% |
| Underprediction | 64.29% | 78.57% |
| P95 underprediction ratio | 93.03% | 93.43% |
| Overprediction | 35.71% | 21.43% |
| Operation-count MAE | 37.50 | 33.21 |
| Future recall | 17.23% | 27.24% |
| Cost-weighted future recall | 38.75% | 41.16% |
| High-cost future recall | 58.90% | 36.33% |
| Mandatory future recall | 76.78% | 84.66% |
| Main Final recall | 100% | 100% |
| Search Final recall | 0% | 33.33% |
| Unexpected predicted cost | 0 | 0 |

These columns compare causal checkpoints in the same execution, not two software versions. The 14-query targeted workload contains substantially more Search Agent work than v2, so its aggregate errors are not a controlled before/after comparison with the v2 12-query set.

Lifecycle: 787 transitions; 288 additions, 213 starts, 256 completions, 30 supersedes. Terminal removal count = 286; QP placeholder replacement = 30. Budget recomputation = 416/416 (100%); stale count = 0; unchanged SAME_ESTIMATED_COST = 321.

Search target achieved: 6 traces contain search.plan and 6 contain search.final. Total search.plan = 59, search.final = 16. Product queries produced 12 initial searches, 22 different-need transitions, 154 same-need refinements and 1 exact duplicate. Refinement classification describes changed queries/constraints, not proof that every repeated search was necessary.

## Findings and limitations

1. Lifecycle removal and explicit budget recomputation are functioning. Lower unexpected cost alone is insufficient: complex-flow recall still fails the requested gates.
2. Collapsing repeated tool names to a set predicted one child flow for a batch of several dispatches. This is fixed and independently tested.
3. The first collection contains 187 product embeddings and 187 product reranks; Main planning = 62 calls and Search planning = 59. Repeated names indicate multiple operations, not necessarily duplicate accounting. Some Search Agents hit the existing six-round limit. Normal refinement, evidence insufficiency and no-new-information reasoning need further separation.
4. Current lifecycle matching consumes the oldest node with a matching operation name. It does not yet prove exact per-child ownership under concurrency. The Search Final cancellation uses the same aggregate convention. This remains a blocker for action-driving policy.
5. Current prediction-reason precision matches a later operation name and can overstate precision under concurrency; QP placeholder superseding is separately reported. Do not interpret its 100% values as a logical-ID accuracy gate.
6. Cost-weighted overlap is an offline diagnostic weighted by observed costs. Actual costs are not inputs to the online prediction.
7. Planned budget is presently recomputed from future work, while the legacy exceed metric compares it to final request total. Its scope needs alignment before using the exceed rate as an independent release gate.
8. Final route and expected benchmark buckets are descriptive; expected DECOMPOSE is not proof that QueryProcessor actually decomposed the request.

## Gates

Tokenizer Golden Parity and Retrieval Quality Regression remain NOT_RUN for this iteration. Predictor high-cost/mandatory recall is below target. No profiles are promoted to action-driving on this evidence. Phase 3 stays NO_GO.

Before a full 67×2, complete the direct-DeepSeek Golden parity suite and frozen retrieval regression. This smoke dataset has no relevance labels and cannot establish retrieval quality.

Artifacts: `phase25-causal-smoke-v3-targeted.jsonl`, `phase25-causal-smoke-v3-runs.json`, `phase25-causal-smoke-v3-report.json`, `phase25-causal-smoke-v3-replay.json`, `phase25-causal-smoke-v3-replay.md`.

## Cardinality repair verification: 10 repeated cases

Second collection: 10/10 requests successful, 10/10 traces eligible; accounting errors, reservation leaks, duplicate accounting and stale executions all zero. The same prompt candidate was pinned for both runs. No prompt was published.

| Metric at first informed revision | First collection, same 10 cases | Repair verification |
|---|---:|---:|
| Request MAE | 196,082 | 113,876 |
| Request MAPE | 66.84% | 47.48% |
| Underprediction | 80% | 80% |
| Overprediction | 20% | 20% |
| Operation-count MAE | 42.60 | 38.20 |
| Future-operation recall | 28.42% | 25.16% |
| Cost-weighted future recall | 41.75% | 46.93% |
| High-cost future recall | 31.45% | 56.22% |
| Mandatory future recall | 78.53% | 94.30% |
| Main Final recall | 100% | 100% |
| Search Final recall | 33.33% | 83.33% |
| Unexpected predicted cost | 0 | 0 |

These are descriptive repeated-run results. Model execution graphs and actual token totals changed between runs; improvements cannot all be attributed to the code repair. No uniform safety factor was increased. The original v2 benchmark was not rerun, so the original v2 simple-DIRECT regression gate is not proven by this experiment.

Within the second collection itself, revision 0 → first informed revision yields MAE 175,259 → 113,876; MAPE 78.40% → 47.48%; operation-count MAE 44.6 → 38.2; cost-weighted recall 34.38% → 46.93%. Underprediction changes 60% → 80%, P95 underprediction ratio 90.94% → 92.46%, and overprediction 40% → 20%. Lower overall error therefore does not establish tail safety.

Lifecycle: 1,325 transitions; 506 additions, 339 starts, 434 completions, 29 supersedes, 17 cancellations. Terminal removals = 480; QP replacements = 29. Material budget revisions = 562, recomputed = 562 (100%), stale = 0; SAME_ESTIMATED_COST unchanged = 378.

Search target remains achieved in 6 traces. Search Final is fully predicted at the first informed checkpoint in 5/6 Search cases. `p25v3-search-06` has Search Final recall = 0 there because its early QueryProcessor checkpoint precedes the dispatch. This is a causal visibility limitation, not justification for injecting the final route at request start.

Product attribution: 8 initial searches, 21 different needs, 114 same-need refinements, 28 same-need evidence-insufficient searches and 1 exact duplicate. Search continuation reason has diagnostic name-match precision 62/75 = 82.67%; product-emitted reason 336/344 = 97.67%. The logical-ID precision limitation above still applies.

The three expected-simple cases in this repetition have MAE 10,349 and MAPE 51.58%; two still overpredict. Complex requests remain dominated by future planning/retrieval rounds that are only revealed gradually. Do not learn these as a fixed 200K product-search profile.

Validation: 34 focused regression tests passed. Final decision: **NO_GO**. Continue shadow-only. Remaining gates: exact concurrent child-flow identity and operation prediction, cost-weighted recall >=80%, mandatory recall 100%, tail underprediction control, planned-budget metric scope alignment, direct-DeepSeek Golden Tokenizer Parity and frozen Retrieval Quality Regression.

Second-run artifacts: `phase25-causal-smoke-v3-cardinality-r2-runs.json`, `phase25-causal-smoke-v3-cardinality-r2-report.json`, `phase25-causal-smoke-v3-cardinality-r2-replay.json`, `phase25-causal-smoke-v3-cardinality-r2-replay.md`.
