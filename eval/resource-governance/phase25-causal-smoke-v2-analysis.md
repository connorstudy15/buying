# Phase 2.5 causal-smoke v2 analysis

## Decision

- Governor remains `shadow-only`.
- Phase 3 remains `NO_GO`.
- Do not run the full 67 x 2 benchmark yet.
- Retrieval Quality Regression and DeepSeek V4.1 Golden Tokenizer Parity remain `NOT_RUN`.

## Scope and integrity

- 12 targeted requests completed with 0 request errors.
- 12/12 Langfuse traces were fetched by manifest trace id.
- 12/12 traces passed strict `plan_trace_integrity=VALID`.
- 140 plan revisions were reconstructed from an explicit declared operation count and indexed operation attributes.
- Replay followed event order and did not consume final route, final subquery count, or later operations before they became visible.
- 68 product-search trace events were captured with query hash, constraint signature, search iteration, and result/evidence reference metadata.

Historical r4/r5 traces without the indexed-operation integrity contract remain excluded from strict replay. They are not repaired or guessed.

## Revision 0 vs first informed revision

| Metric | Revision 0 | First informed | Change |
|---|---:|---:|---:|
| Request MAE | 16,852.6 | 17,834.1 | worse by 981.5 |
| Request MAPE | 46.16% | 59.25% | worse by 13.09 pp |
| Underprediction rate | 50.00% | 33.33% | better by 16.67 pp |
| Underprediction P95 ratio | 47.83% | 28.42% | better by 19.41 pp |
| Overprediction rate | 50.00% | 66.67% | worse by 16.67 pp |
| Operation-count MAE | 5.50 | 2.83 | better by 48.5% |
| Operation-count P95 error | 12 | 6 | better by 50% |
| Remaining main-plan count MAE | 1.25 | 0.75 | better by 40% |
| Future-operation recall | 28.91% | 68.03% | better by 39.12 pp |
| Future-operation precision | 100.00% | 76.11% | worse by 23.89 pp |
| Cost-weighted future recall | 58.61% | 84.34% | better by 25.73 pp |
| Cost-weighted future precision | 100.00% | 83.87% | worse by 16.13 pp |
| High-cost future recall | 88.46% | 91.55% | better by 3.09 pp |
| Mandatory future recall | 100.00% | 100.00% | unchanged |
| Main Final recall | 100.00% | 100.00% | unchanged |
| Mean missing remaining cost | 27,683.6 | 9,230.7 | better by 66.7% |
| Mean unexpected predicted cost | 0 | 4,684.8 | new overprediction |
| Planned-budget exceed rate | 41.67% | 41.67% | no improvement |

Interpretation: the runtime-informed plan predicts substantially more of the real future execution graph and protects expensive/mandatory work better. It does not yet predict total request cost more accurately because it trades underprediction for systematic overprediction, especially on simple requests.

## Bucket findings

### Knowledge DECOMPOSE

- MAE improved from 15,827.5 to 15,226.0.
- Underprediction rate improved from 66.67% to 33.33%.
- Worst underprediction reduced from 38,223 tokens to 20,239 tokens.
- Overprediction rate increased from 33.33% to 66.67%.

### Simple DIRECT

- MAE worsened from 17,877.7 to 20,442.2.
- MAPE worsened from 69.22% to 89.01%.
- Underprediction magnitude became small in the remaining underpredicted cases, but the predictor overpredicted four of six cases.

### Cross-evidence

- MAE improved from 22,913.8 to 14,567.2.
- Underprediction rate improved from 100% to 60%.
- Underprediction P95 fell from 38,223 to 20,239 tokens.

The current update helps complex/cross-evidence work, but applies too much of that protection to simple work.

## Operation attribution

| Operation | Count | Token P50 | Token P95 | Notes |
|---|---:|---:|---:|---|
| `embedding.product_query` | 34 | 30 | 35 | low cost, often repeated |
| `reranker.product` | 34 | 1,197 | 1,256 | medium cost, paired with product query |
| `main.plan` | 27 | 10,974 | 20,183 | dominant variable high-cost operation |
| `reranker.knowledge.need` | 17 | 3,469 | 3,601 | scales with information needs |
| `main.final` | 12 | 17,212 | 26,536 | mandatory and always protected |
| `query_processor.decompose` | 6 | 1,389 | 1,602 | route-revealing operation |
| `query_processor.direct` | 4 | 941 | 1,101 | route-revealing operation |
| `query_processor.rewrite` | 1 | 1,162 | 1,162 | too few samples for calibration |

There are no unknown/unclassified actual resource operations in this 12-trace sample. The main residual is not tokenizer noise; it is prediction of additional planning rounds and speculative future operations.

## Planning-round findings

- Every request starts with one `main.plan`.
- Additional `main.plan` most often follows `reranker.product` (9 transitions) or `reranker.knowledge.need` (4 transitions).
- One `main.plan -> main.plan` transition occurred and should be reviewed as a possible repeated reasoning round.
- No `search.plan` operation occurred in this smoke set, so Search Agent planning calibration is still unvalidated.
- Potential repeated executions: `main.plan=15`, `embedding.product_query=24`, `reranker.product=24`, and `query_processor.direct=1`.

The product repeats were classified as 24 refinements and 0 exact duplicate candidates. This means the new metadata can distinguish query/constraint changes, but it does not yet prove every refinement was necessary. The current tool contract exposes `information_need_id=overall`; true per-need attribution requires the caller to pass an explicit need id.

## Revision convergence example: v4-038

- Revision 0 knew only the bootstrap plan. It missed 19 operations and had 33.2% cost-weighted future recall.
- Revisions 2, 6, and 10 reacted to emitted tool calls and reduced missing operations from 16 to 10 to 4.
- Revision 15 received the QueryProcessor result (`knowledge_decompose`, 3 needs); cost-weighted future recall reached 100%.
- Later revisions retained perfect recall but precision fell because already-consumed product embeddings and one speculative `main.plan` remained in the predicted future graph.

This proves the plan consumes runtime state and can converge without looking ahead. It also exposes a remaining state-transition bug: completed/obsolete future nodes are not always removed promptly.

## Budget revision response

- Material future-graph changes: 115 revisions.
- Revisions where planned budget also changed: 75.
- Response rate: 65.22%.

This is insufficient for action-driving policy. A future graph can change while the rounded/profile-derived budget remains numerically unchanged, but the current 34.78% non-response is too large to treat only as rounding. The next calibration should record an explicit reason for an unchanged budget: same cost class, profile floor/cap, safety-floor dominance, or stale recomputation.

## Case-level result

Absolute request-token error improved in 5/12 cases (`v4-006`, `v4-026`, `v4-027`, `v4-028`, `v4-038`) and worsened in 7/12. The strongest improvement was `v4-038` (20,974 fewer absolute-error tokens). The largest regression was `v4-047` (20,217 more absolute-error tokens).

Complex cases generally gained future-operation coverage. Simple/short cases were overprotected by speculative `main.plan` and `query_processor.classify` nodes, explaining why graph recall improved while request MAE/MAPE did not.

## Required next calibration

1. Remove or condition the speculative `query_processor.classify` future node when the actual implementation directly records `query_processor.direct/rewrite/decompose`.
2. Decrement completed product embedding/rerank nodes from the future graph at `operation_completed`.
3. Predict an additional `main.plan` only from concrete evidence: a tool result requiring synthesis, evidence insufficiency, a new information need, or an explicit retry/loop signal.
4. Add an explicit budget non-response reason and require recomputation on every material graph revision.
5. Collect targeted Search Agent traces because this sample contains no `search.plan/search.final`.
6. Repeat this 10-15 trace causal smoke after those changes. Only then consider the full 67 x 2 run.

## Gates

- Accounting reconciliation: PASS (0 errors).
- Trace revision integrity: PASS (12/12 VALID).
- Mandatory/Main Final protection: PASS in this sample.
- Future graph convergence: PARTIAL PASS.
- Request cost accuracy: FAIL.
- Planned-budget responsiveness: FAIL.
- Retrieval Quality Regression: NOT RUN.
- DeepSeek V4.1 Golden Tokenizer Parity: NOT RUN; `DEEPSEEK_V41_TOKENIZER_PRIMARY=0` remains required.
- Phase 3: **NO_GO**.
