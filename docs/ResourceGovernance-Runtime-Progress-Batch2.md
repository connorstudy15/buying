# Phase 2.5 第二批：RuntimeState / ProgressDetector

## 范围

只增加因果状态和进展诊断。不新增 LLM，不改变 FutureWorkPlan、预算、检索深度、
RRF、reranker、mandatory operation 或订单状态。Governor 继续 shadow-only；
Phase 3 继续 NO_GO；80K 仍仅观测；tokenizer PRIMARY 不变。不跑完整 67×2。

## 新代码

- `app/infrastructure/resource_governance/runtime.py`：请求内、按 child flow 隔离的
  RuntimeStateStore、不可变 RuntimeObservation / RuntimeState、确定性 ProgressDetector。
- middleware：在已许可工具开始、最终结果/异常、模型调用成功完成时采集。
- governor：QP 返回后登记当前已知的必要 need；RuntimeState 只诊断，不驱动预算或策略。
- report / replay：读取 runtime_progress_events，汇总进展和 refinement 分类、
  ZERO_PROGRESS 后同一 child 是否仍出现 continuation。旧 trace 标记 NOT_AVAILABLE。

## 语义

快照包含当时已知 route、operation、已登记必要 need 数/覆盖数、各 Agent planning
round、context tokens、工具/need/query/constraint 标识、新证据数、充分性、
progress、zero-progress streak、loop risk、mandatory action 状态。

关键未知状态不能补成 false：

- need_scope_complete 固定为 false：已登记 QP needs 不一定覆盖整个用户意图。
- optional_need_remaining、evidence_sufficient、pending_mandatory_action 无可靠来源时为 null。
- context_tokens 取模型实际 prompt usage，是模型上下文大小，不是请求总 token。
- 新 chunk / 商品结果只算“新召回证据”，不自动算 relevant 或 covered。
- 检索分数变化不算新知识证据；opaque result_ref 变化也不算新证据。
- price/stock 查询需要 freshness，不能仅凭相同参数判定 EXACT_DUPLICATE。
- 知识查询 freshness 默认未知，同样不能擅自认定重复浪费。

Progress 分类：

- HIGH：显式已验证 coverage / required evidence、充分性提升或交易状态推进。
- MEDIUM：新增已登记必要 need，或明确针对必要 need 的新有效 action。
- LOW：新增未验证相关性的召回证据、requiredness 未知的新许可 action。
- ZERO：明确无 freshness 需求、相同检索、无新证据；或显式声明完整观测且无状态变化。
- UNKNOWN：没有足够观测，或者调用失败。UNKNOWN 不等于 ZERO。

Refinement 分类支持 USEFUL_REFINEMENT、NECESSARY_BUT_NO_RESULT、
LOW_VALUE_REFINEMENT、EXACT_DUPLICATE、UNKNOWN。前几种强语义需要显式证据：
当前线上链路没有可靠 relevance/sufficiency/transaction advancement 判定的部分，
不自动生成这些标签。changed query 本身不证明 useful，也不证明 waste。

ZERO streak 按 child + tool + need 独立维护，中间的模型事件不会冒充检索取得进展。
连续 ZERO >= 2 仅标记 HIGH loop risk，绝不停止执行。

## Langfuse 查看

重启后新 trace 增加 `resource.runtime_progress` 节点。
Attributes 中 `globex.resource.runtime_state` 包含 before/after、reason、progress、
refinement；这些是内容无关的技术数据，脱敏后即使 content_mode=off 也可导出。
开发模式的 observation output 是否展示取决于现有内容模式白名单，Attributes 是可靠入口。

记录有 event_id、flow_id、sequence 和采集时间；旧 history 不被后续状态反写。
只保存 fingerprint 和计数，不保存原始问题、API key、商品描述或异常正文。

## 验证与未完成项

本批先做离线语义、并发隔离、adapter、脱敏与不改变业务的回归。未重启服务、
未采新真实 trace，因此不能宣称 MAPE、underprediction 或检索质量改善。
历史 154 个 refinement 不能靠这些新字段追溯生成可靠 relevance 标签。

NextOperationPredictor、TransitionProfileStore、LoopContinuationPredictor、
FutureCostDistribution 尚未加入；后续应单独校准，并把“实际会不会继续执行”和
“继续执行是否有价值”分开，不因 ZERO 而调低真实执行成本预测。
