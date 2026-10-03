# DECOMPOSE Trigger Holdout

- 20 道口语化问题：10 DIRECT、10 DECOMPOSE。
- 仅依据 QueryProcessor 的决策合同和项目品类范围编写；未读取知识库正文或 gold evidence。
- 冻结后才调用目标 QueryProcessor；不得根据运行结果修改本文件再重报同一 holdout 分数。
- 本集合只评价是否应该拆分，不评价知识召回内容。
- REWRITE 在当前禁用改写实验中按 DIRECT 侧计算；模型异常或校验回退单独计入 fallback，不冒充正确 DIRECT。

验收目标：

- Trigger Precision ≥ 90%。
- Trigger Recall ≥ 90%。
- DIRECT preservation accuracy ≥ 90%。
- 三轮任一轮不得低于上述门槛。
