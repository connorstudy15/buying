# Token Budget × Context Governance：Phase 0～2

本阶段仅做 shadow observation。它会记录真实调用、构建历史画像、预测未来工作并计算“如果执行预算策略会怎么决定”，但不会拒绝调用、切换模型、改写检索参数或影响交易操作。旧 `TokenBudget` 继续保持原开关语义；新 Governor 不接管旧预算。

## 单一事实源

- `UsageLedger`：唯一的已用资源事实源；每个 logical call attempt 只能结算一次。
- `ReservationManager`：唯一的 active reserved resource 事实源。
- `FutureWorkPlan`：唯一的 protected / predicted future work 事实源；`ACTIVE_RESERVED` 只保存 reservation 外键，不参与 active resource 聚合。
- `OperationProfileStore`：历史 operation 成本分布。
- `WorkloadPredictor`：创建和更新未来工作图。
- `ResourcePolicy`：逐维比较 `ResourceEstimate` 与 `BudgetEnvelope`。
- `ContextGovernorAdapter`：operation-specific hard safety 和 counterfactual compaction ROI。

`ResourceEstimate` 不实现大小比较。Chat Token、Embedding Token、Rerank Token、调用次数、金额和延迟分别保存。第一版只有 Chat Token 参与未来 enforcement 判定；金额和延迟仅观察。

## 三个强制不变量

1. 一个 `logical_call_id` 只存在于 `PROTECTED_FUTURE`、`PREDICTED_UNRESERVED`、`ACTIVE_RESERVED` 中的一个 bucket。
2. `try_reserve` 必须在 `asyncio.Lock` 内验证 `expected_plan_revision == current revision`，并重新验证取消状态、依赖和 information need；旧计划返回 `REPLAN_REQUIRED`。
3. 一个 `ACTIVE_RESERVED` operation 必须恰好对应一个 active `Reservation`。重试前必须先把旧 attempt 结算成 actual / estimated / timeout estimated。

## Bootstrap 参数

- Context soft target：48K。
- Provisional high pressure：60K。
- Chat Token absolute hard cap：80K。
- Request 初始假设：一次 `main.plan` + 一次受保护 `main.final`。
- Planning safety factor：1.20。

这些都是当前合理初值，不代表已经由 Trace 证明为最佳值。

## Operation Trace

Langfuse 中新增以下节点：

- `resource.model_operation`：Agent 级逻辑调用，响应含工具调用时标为 `main/search/trade.plan`，否则标为 `*.final`。
- `resource.model_attempt`：真实上游 attempt，包含 attempt 序号、retry、fallback 和 usage source。
- `resource.embedding`：Embedding 请求的调用次数、token（网关无 usage 时明确标为 estimated）和延迟。
- `resource.reranker`：Reranker 文档数、token、usage source 和延迟。
- `commerce.turn`：request 级 plan revision、used / reserved / protected / predicted / projected Chat Token，以及 shadow decision。

检索既有节点 `knowledge.query_processor` 同时记录 `query_processor.direct/rewrite/decompose` operation。所有新字段均为技术元数据，不新增 API key 或正文导出。

## Context Summary ROI

摘要成功时保存 `CompactionBaseline`：scope、旧/新 revision、压缩前后 token、移除的引用以及 estimator version。后续同 scope 模型调用只观察压缩后的真实 input token；未压缩版本由 `TokenEstimator` 根据 baseline 估算。

因此 Trace 字段明确命名为：

- `counterfactual_input_tokens`
- `counterfactual_realized_saving`
- `counterfactual_realized_roi`

它不是 A/B 同时执行得到的直接真实节省。

## Profile Builder

输入必须是不含正文的 JSON 或 JSONL observation：

```powershell
.\.venv\Scripts\python.exe scripts\resource_governance\build_profiles.py observations.jsonl data\resource-profiles.json
```

兼容性 key 使用 environment、component、operation、model、execution path、context/candidate bucket、prompt/policy version 和 `execution_contract_hash`。Git commit 仅保存在 metadata，用于审计，不参与 exact key。

## 历史 Trace 回放

```powershell
.\.venv\Scripts\python.exe scripts\resource_governance\replay_langfuse.py `
  --env-file .env --lookback-days 31 `
  --output eval\resource-governance\phase2-shadow-replay-20261008.json
```

脚本只读取 observation 名称、时间和 usage，不请求或输出提示词、工具 I/O 和业务正文。旧 Trace 没有显式 operation 字段，因此旧数据的 plan/final 重建标为 low confidence；新 Trace 应以显式 operation 为准。

