# Knowledge Benchmark V4 阶段 B 独立审核报告

## 审核依据和隔离

- 阶段 A 冻结 Query SHA-256：`67b452193c53dcccc63fe5a15916e4ab19997125bd6eb1088fd6807268578767`，manifest 记录 `knowledge_body_exposed_before_freeze=false`。
- 旧候选池哈希不匹配，已重建 `candidate_pool_approved.jsonl`；其 manifest 的 `query_sha256` 与冻结 Query 一致。
- 仅使用批准 Query、匹配的候选池、知识正文及标注契约。未读取 `eval/runs/**` 或任何逐题命中、坏案例和指标报告；未运行外部 DeepSeek 标注流程。
- 旧 22 条 Core 原文件未修改，SHA-256：`ac686e08b9114ebfcc8282e4fd80e7d709a777c65d7f1cb707eef321a3321c4c`。

## 结论与分布

- 60 题全部有结论：`model_approved` 20、`model_revised` 25、`model_rejected` 15。`model_revised` 主要表示将确定性答案改为有条件的判断口径；Query 文本未在阶段 B 改写。
- 拒绝 ID：`v4-004`、`v4-009`、`v4-012`、`v4-015`、`v4-019`、`v4-025`、`v4-033`、`v4-036`、`v4-039`、`v4-050`、`v4-r001`、`v4-r003`、`v4-r004`、`v4-r005`、`v4-r013`。
- 阶段 A 题型保持：single 22、cross 20、implicit 10、unanswerable 7、policy boundary 1。
- 策略真值保持：DIRECT 33、DECOMPOSE 20、BYPASS 7。
- 阶段 B 没有新的 single/cross 改类或策略改动。阶段 A 已改类 `v4-019`（single→cross）和 `v4-035`（cross→single）；其中 `v4-019` 在正文核验后因缺少天幕本身重量证据被拒绝。
- 阶段 A 没有 `answerability` 字段，因此不存在可核对的“answerable→conditional/unanswerable”历史变更。本轮判为 conditional 的 ID：`v4-004`、`v4-009`、`v4-012`、`v4-015`、`v4-017`、`v4-019`、`v4-021`、`v4-022`、`v4-024`、`v4-025`、`v4-027`、`v4-028`、`v4-029`、`v4-030`、`v4-031`、`v4-033`、`v4-036`、`v4-037`、`v4-038`、`v4-039`、`v4-041`、`v4-043`、`v4-044`、`v4-045`、`v4-046`、`v4-047`、`v4-048`、`v4-049`、`v4-050`、`v4-051`、`v4-060`、`v4-r001`、`v4-r003`、`v4-r004`、`v4-r005`、`v4-r009`、`v4-r011`、`v4-r012`、`v4-r013`、`v4-r014`；unanswerable 的 ID：`v4-054`、`v4-055`、`v4-057`、`v4-058`、`v4-r015`、`v4-r016`、`v4-r017`。

## 证据和难负例

- `graded_relevance` 是唯一文档级真值，`relevant` 逐题由 grade≥2 自动生成。证据原文和标题用项目 `inspect_evidence` 逐条校验，证据 ID 及 quote SHA-256 用项目函数生成。
- 难负例共 18 个 case，类型分布：{"same_attribute_wrong_product": 4, "same_attribute_wrong_category": 1, "same_category_generic": 2, "partial_cost_only": 1, "same_term_partial": 1, "same_topic_wrong_scope": 1, "generic_cross_border": 1, "tax_example_wrong_scope": 1, "generic_voltage_only": 1, "same_topic_missing_price": 1, "same_travel_wrong_constraint": 1, "wrong_material_scope": 1, "static_guidance_not_authority": 1, "same_material_wrong_product": 1}。仅保留在匹配候选池内且 grade=1 的具体易混淆来源，均不与正例重叠。
- 不能完整覆盖两个独立需求的 cross ID：`v4-019`、`v4-025`、`v4-033`、`v4-036`、`v4-039`、`v4-r013`；隐含约束缺一项证据的 ID：`v4-050`。这些题均为 `model_rejected`，保留部分证据仅供复核，未追加到合并候选集。
- 候选池疑似漏掉的真阳性：`v4-r011` 的 `cross-border-guide.md`。该来源仍按正文证据保留为正例，不能因未召回而降级。

## 低置信度、冲突与用户决定

- 置信度低于 0.85 的 ID：`v4-004`、`v4-009`、`v4-012`、`v4-015`、`v4-019`、`v4-025`、`v4-033`、`v4-036`、`v4-039`、`v4-044`、`v4-045`、`v4-047`、`v4-050`、`v4-r001`、`v4-r003`、`v4-r004`、`v4-r005`、`v4-r009`、`v4-r011`、`v4-r012`、`v4-r013`。
- 冲突清单共 23 题：`v4-004`、`v4-009`、`v4-012`、`v4-015`、`v4-019`、`v4-025`、`v4-033`、`v4-036`、`v4-039`、`v4-044`、`v4-045`、`v4-047`、`v4-050`、`v4-060`、`v4-r001`、`v4-r003`、`v4-r004`、`v4-r005`、`v4-r009`、`v4-r011`、`v4-r012`、`v4-r013`、`v4-r014`。逐题原因见 `label_conflicts.jsonl`。
- 请用户决定是否移除 15 道拒绝题，或补充经核验的正文后重新审核；并复核条件性政策、航司、商品参数边界及 `v4-r011` 候选池漏召回。模型不会替用户批准争议标签。

## 机械校验与验收

- 60 条结论、唯一 ID/Query、证据连续原文、真实标题、证据 ID/hash、grade 与 `relevant` 一致、难负例等级与不重叠、unanswerable 无正证据、策略枚举、旧 Core 哈希不变均通过本地机械检查。
- 保留题的 cross/implicit 每一 hop 均有正证据；拒绝题中 6 道 cross 和 1 道 implicit 缺完整证据。合并候选集为旧 22 条加通过的 45 条，共 67 条。
- 指定测试：`tests/test_knowledge_evidence.py`、`tests/test_eval_category_runner.py`、`tests/test_knowledge_query_transform.py`，**32 passed**。
- **未满足全部阶段 B 验收标准**：新增 60 题中有 15 题不适合保留为可靠知识检索真值，故不能宣称 60 题全部可用或新 benchmark 已冻结。所有新题的 `label_status` 均为 `reviewed_candidate`。

本报告只表示已通过模型独立审核。冲突和拒绝题仍需用户决定；候选集尚未冻结，也不具备上线代表性的批准结论。
