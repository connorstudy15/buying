# DECOMPOSE Trigger Holdout

- 20 道口语化问题：10 DIRECT、10 DECOMPOSE。
- 仅依据 QueryProcessor 的决策合同和项目品类范围编写；未读取知识库正文或 gold evidence。
- 冻结后才调用目标 QueryProcessor；不得根据运行结果修改本文件再重报同一 holdout 分数。
- 本集合只评价是否应该拆分，不评价知识召回内容。
- REWRITE 在当前禁用改写实验中按 DIRECT 侧计算；模型异常或校验回退单独计入 fallback，不冒充正确 DIRECT。

指标口径：

- `Model Decision Recall`：只看模型原始结构化输出是否正确选择 `DECOMPOSE`，不受后续 validator 或 fallback 影响。
- `Effective Decompose Recall`：模型输出经过格式校验、约束校验和 fallback 后，最终真正进入 `DECOMPOSE` 的比例。
- 两者之间的差值表示“模型判断正确，但执行链路没有采用”的损失。
- 旧字段 `Recall` 暂时作为 `Effective Decompose Recall` 的兼容别名；新报告必须同时显示上述两个指标。

验收目标：

- Trigger Precision ≥ 90%。
- Model Decision Recall ≥ 90%。
- Effective Decompose Recall ≥ 90%。
- DIRECT preservation accuracy ≥ 90%。
- 三轮任一轮不得低于上述门槛。
