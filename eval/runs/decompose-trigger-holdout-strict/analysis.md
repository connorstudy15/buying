# DECOMPOSE 触发盲测与修复结论

## 结论

首次严格盲测的真实结果不是满分：三轮均为 Precision 100%、Recall 90%、DIRECT 保持率 100%、fallback 5%。唯一失败题是 `trigger-h014`，三轮均触发 `query_processor_constraint_drift`。

根因不是模型误判 DIRECT，而是确定性校验器把疑问表达“能不能”中的“不能”误当成强否定约束。模型生成“是否可以携带”后，校验器认为否定条件丢失并降级到 legacy 检索。

修复后在同一数据集做三轮回归验证，Precision、Recall、DIRECT 保持率均为 100%，fallback 为 0。由于数据已经被观察过，这一结果只能称为回归验证，不能称为第二次盲测。

## 首次严格盲测

- 数据：20 题，其中 DIRECT 10 题、DECOMPOSE 10 题。
- 重复：3 轮，共 60 次 QueryProcessor 调用。
- Precision：三轮均 100%，没有把 DIRECT 题误拆。
- Recall：三轮均 90%，每轮漏掉 `trigger-h014`。
- DIRECT 保持率：三轮均 100%。
- fallback：三轮均 5%。
- P50：约 1.08～1.11 秒。
- P95：约 1.39～1.51 秒。
- Langfuse run ID：`decompose-trigger-20261004021707-e09e3cfb`。

原始证据见 `trigger-holdout-20261004-021813.json` 和 `trigger-holdout-20261004-021813.md`。

## 修复内容

约束校验现在先排除“能不能、可不可以、是否能、能否、可否”等可行性疑问表达，再检查真正的强否定。`不要、不能、不含、没有、不得、禁止` 等明确约束仍然受到保护。

## 修复后回归

- 三轮 Precision：100%。
- 三轮 Recall：100%。
- 三轮 DIRECT 保持率：100%。
- 三轮 fallback：0%。
- P50：约 1.03～1.05 秒。
- P95：约 1.27～1.42 秒。
- Langfuse run ID：`decompose-trigger-20261004021932-188c9bf4`。

回归原始证据位于 `../decompose-trigger-holdout-regression/trigger-holdout-20261004-022037.json`。

## 如何解读

当前 Prompt 在这 20 题上没有观察到“误拆”；首次漏拆来自校验器而非模型决策，且通用修复后稳定消失。这个结果支持把当前 Prompt 和校验逻辑作为 V3 候选，但 20 题仍然较小。若之后继续根据这些题调整逻辑，这组数据应转为稳定回归集；下一次发布前应另建一组未见过的盲测题，避免在同一批题上反复调优造成虚高。
