# Phase 2.5 第三批：NextOperation / LoopContinuation

## 边界

本批新增旁路预测，Governor 仍 shadow-only、Phase 3 仍 NO_GO。
不修改 FutureWorkPlan、Accounting/Reservation、检索参数、mandatory flow、80K 策略
或 tokenizer PRIMARY。没有新增 LLM，也没有训练神经网络。

本批没有把概率或剩余轮数加入请求总预算；避免与既有节点重复计费，也不对 mandatory
成本作概率折扣。FutureCostDistribution 和正式 graph integration 留待验证后单独实施。

## 实现

- `app/infrastructure/resource_governance/continuation.py`
  - TransitionProfileStore：独立历史统计，支持序列化、版本检查及重复样本检查。
  - NextOperationPredictor：规则 bootstrap + 历史频数平滑 + 四级回退。
  - LoopContinuationPredictor：同一 child flow 后续 Main/Search plan 轮数的历史分布。
  - ContinuationDiagnostics：冻结 profile 快照，不在线学习。
- RuntimeState 增加持续的 agent_role，避免 QP 事件把 Search 的角色覆盖成 unknown。
- governor 将 forecast 附在当前 runtime snapshot，导出到 Langfuse。
- 修正 task_dispatch 的 runtime 归属：许可/返回属于调用方，worker 事件属于 child。
  否则 task_dispatch.result 出现在 search.final 后会污染 child lifecycle 标签。
- `scripts/resource_governance/evaluate_continuation.py`：校准/验证分离的离线评测入口。

## 预测范围与因果性

NextOperation 是“当前 snapshot 之后，同一 flow 的下一条可观测完成事件”，
不是全局下一 HTTP API 调用；不把其他并发子 Agent 的事件当成自身的下一步。
tool.permitted 是有效 checkpoint，但不是完成事件标签。

Loop count 也是同一 flow 内的后续完成轮数，不包括尚未派发的其他 Agent。
它不等于请求级全部 remaining operations。

特征只使用当前保存的 `after` snapshot。离线 future 只用于生成 label，
不使用最终 route、最终 subquery count 或最终 operation count 作早期特征。
序列缺口、重复 sequence、terminal 后仍有事件的 child 不作为完整标签序列。
没有 final 的尾部为 censored，不标记成零轮/END。

## 分层与置信度

Next profile 分层为：

1. role + last operation + known unresolved state + sufficiency + current route
2. 去掉 route
3. 再去掉 sufficiency
4. role + last operation

Loop 在上述层级前增加粗粒度 progress、streak、当前 round bucket、new evidence。
ZERO_PROGRESS 不人为降低继续执行概率；PIVOT_CANDIDATE 只是独立价值诊断。

每个 profile 记录 event sample count 和 independent case/group count。
至少 30 样本且 10 个独立 group 才标 MEDIUM；单一长请求产生 100 多个事件仍不能升档。
少量样本为 LOW，完全缺失为 BOOTSTRAP。当前不发 HIGH。

Next 分布有 5 个明确 bootstrap 伪计数，避免 1/1 -> 100% 的错误自信。
bootstrap 概率是规则先验，不是已校准真实概率。

Loop 无样本时 expected/P50/P80/P95 均为 null，不编造尾部。
P50/P80 至少 30 样本 + 10 group；P95 至少 100 样本 + 30 group。
即便达到数量要求，quantile 仍是 shadow empirical estimate，不代表已通过尾部安全 Gate。
已完成 final 的 END/零剩余轮数属于 protocol terminal rule，不算统计 HIGH confidence。

## 评测与运行

输入兼容现有 Phase 2.5 JSON 中的 `request_rows`，每条需含新
runtime_progress_events。必须使用不同 case/group 的校准和验证文件；
重复运行同一 query 的两个 trace 不能跨两个集合。

PowerShell 示例（文件名为待采集后建立的独立文件，不表示已经存在）：

```powershell
.\.venv\Scripts\python.exe scripts/resource_governance/evaluate_continuation.py --calibration eval/resource-governance/continuation-calibration.json --validation eval/resource-governance/continuation-validation.json --output eval/resource-governance/continuation-validation-report.json --profile-output eval/resource-governance/continuation-profiles.json
```

输出包括：

- Next top-1 accuracy / top-3 recall
- BOOTSTRAP/LOW/MEDIUM/HIGH、last operation 分桶及各桶 N
- Main/Search remaining-round MAE 和可评估样本量
- another-plan probability 的分箱校准
- P50/P80/P95 empirical coverage 和支持样本量
- 相同验证集上的 bootstrap baseline
- source trace/group provenance 与独立 profile artifact

final -> END 的简单协议样本不计入 accuracy，避免抬高指标。
没有新 instrumentation 的旧 trace 返回 NOT_AVAILABLE，而不是伪造成功结果。

## Langfuse

重启后新 trace 的 `resource.runtime_progress` 节点：

- `globex.resource.continuation_forecast`：next distribution、confidence、sample count、
  hierarchy level、remaining rounds、PIVOT value diagnostic。
- `globex.resource.runtime_state`：before/after + forecast。

这些字段作为有界、脱敏的技术 JSON，在 content_mode=off 也保留。
当前线上接线默认使用空 profile / bootstrap。离线训练的 artifact 不会自动热加载；
不能把 artifact 存在误当成在线已完成真实校准。

## 验证状态与下一步

本节记录编码完成时的状态。后续已执行真实 targeted smoke，结果与失败样本说明见
[Continuation targeted smoke 结果](ResourceGovernance-Continuation-Targeted-Results.md)。
采集尝试 16 条，有效完成 11 条，Phase 3 仍为 NO_GO；以下未采集说明不再代表最新状态。

本批仅离线测试；未重启服务、未运行 12～20 条真实 targeted smoke、未跑 67×2。
因此没有真实 top-1、轮数 MAE 或 request MAPE 改善结论。

下一步应先重启并验证 trace 完整性，然后采集不同 case 的校准/验证数据，
确认 child sequence、snapshot、forecast 不丢失，完成小样本隔离评测。
在有效性验证前，不将这些预测添加到正式 future graph 或预算。
