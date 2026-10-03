# Knowledge Eval v5 证据覆盖契约

本文件是 v3 冻结标注契约的增量，不修改 `eval/knowledge/v3/LABELING_CONTRACT.md` 及其哈希。

## 两个正交字段

不要用一个互斥 `query_type` 同时表达“覆盖多少”和“为什么缺失”。

`answerability` 描述证据覆盖程度：

- `complete`：每个 `required_information_need` 都有至少一条 grade≥2 的 gold evidence；
- `partial`：至少一个 need 有 gold evidence、至少一个 need 没有；
- `none`：所有必要 need 都没有 gold evidence。

`missing_reason` 描述不完整原因：

- `null`：只允许用于 complete；
- `knowledge_gap`：问题合理，但当前 KB 缺少知识；
- `missing_user_context`：缺少用户、商品、航班、目的地等必要输入；
- `realtime_required`：结论依赖实时或未来数据；
- `external_authority_required`：必须由航司、海关、监管机构或承运商等当前权威来源确认。

每个 `required_information_need` 必须声明稳定 `need_id` 和 `gold_evidence_ids`。缺失 need 使用空数组，
不能用主题相关的 grade 0/1 文档伪造成正证据。

## 计分

- complete：进入普通 Recall / All-Evidence Recall；
- partial：不混入普通 Recall，单独报告 Available Evidence Recall 和全部 need 的 Information Need Coverage；
- none：只进入拒答/澄清专项，不混入普通 Recall；
- `missing_reason=knowledge_gap` 的 case 保留在 Knowledge Gap Benchmark，不进入普通发布门禁。

Missing Need Detection、False Complete Answer Rate、Correct Escalation Rate 必须观察 Agent 最终回答或动作；
裸检索 runner 一律报告 `n/a`，不得依据召回结果推断模型已经意识到缺失。
