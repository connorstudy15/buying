# Phase 2.5 — identity / budget scope batch 1

This batch remains observational: no request rejection, mandatory cancellation,
retrieval parameter change, Phase 3 activation, or tokenizer PRIMARY activation.
Ledger and ReservationManager settlement semantics are unchanged.

## Identity

- AgentScope `on_acting` binds an execution ContextVar from the actual validated
  ToolCallBlock ID, without adding model-visible tool parameters.
- Each dispatch uses `dispatch:<tool_call_id>` as its child flow identity.
- Predictor reads already-emitted dispatch arguments to distinguish Search and
  Trade. Trade costs are explicitly bootstrap transfers, not calibrated profiles.
- Parallel knowledge tools each receive their own QP placeholder. A QP result
  supersedes only placeholders in its flow/tool scope. Rerank predictions are
  namespaced by flow/tool/need; runtime need IDs participate in start matching.
- Embedding/reranker actual HTTP IDs bind to a predicted node at start. Completion
  consumes this binding, not the oldest node of the same name. Unbound actual
  IDs cannot consume another call's prediction.
- Child finals remove only that child's unstarted continuation predictions.
- Final operation types for Agent model calls are known only from the response;
  these are reported as SCOPED_OPERATION, not EXACT_BOUND. Actual model call IDs
  are retained separately. This does NOT claim exact predictive foresight.
- Legacy traces lacking these identities remain NOT_AVAILABLE. Legacy name-only
  methods remain for existing offline fixtures; they do not establish exact
  concurrency correctness for historical traces.
- Failed/timeout HTTP operations can remain unresolved STARTED predictions;
  do not interpret this as successful completion or verified provider usage.

## Budget scopes

`planned_chat_limit` / `planned_budget_chat_tokens` retain their previous meaning
(scaled unstarted future chat cost), with an explicit scope annotation.

New observational fields:

    planned_remaining_chat_budget
      = scaled unstarted future chat cost + active reservation + shadow inflight
    planned_total_chat_budget
      = settled ledger chat usage + planned_remaining_chat_budget

Shadow inflight includes only STARTED, non-reserved predicted nodes. Unknown or
unmatched calls still constitute prediction error; the fields are estimates, not
claims of complete execution coverage. Embedding/rerank tokens are not chat tokens.

Replay compares final chat usage with total chat budget, not remaining budget.
Actual remaining chat usage equals final actual minus ledger-settled usage at the
checkpoint. Legacy reports without the new total budget produce null exceed
status, not a fabricated pass/fail. End timestamps include inflight operations in
remaining-operation diagnostics; traces lacking endTime remain legacy proxies.

## Verification and limits

Run the offline suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_resource_execution_identity.py tests/test_resource_governance.py tests/test_causal_replay_metrics.py tests/test_resource_phase25.py tests/test_resource_profile_replay.py tests/test_execution_graph_audit.py tests/test_tracing.py tests/test_tools_and_eventbus.py -q
```

This batch does not claim improved request MAPE or retrieval quality. Those require
new real traces after service restart. No full benchmark, large training, or live
smoke is run here. ProgressDetector, transition/loop predictors and probabilistic
cost distributions remain a later batch.
