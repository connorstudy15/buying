# 品类知识库召回评测报告（2026-10-03 18:06:23）

标注集 `eval\knowledge\v5\knowledge_eval_partial_coverage_2.jsonl`，正例 0 条。兼容文档级指标；存在 evidence_ground_truth 时同时按原文证据评分。

| 指标 | 值 | 阈值 |
|---|---|---|
| Recall@3 | 0.000 | ≥ 0.75（阻断） |
| Precision@3 | 0.000 | ≥ 0.45（阻断） |
| MRR | 0.000 | ≥ 0.65（阻断） |
| NDCG@3 | 0.000 | ≥ 0.7（阻断） |
| Graded nDCG@3 | n/a | 0–3 级相关性，观察项 |
| 不可回答准确率 | n/a | 未启用 |
| 政策拒答准确率 | n/a | 未启用 |
| Evidence Recall | n/a | 观察项 |
| All-evidence Recall | n/a | 观察项 |
| Hard-negative hit rate | n/a | 越低越好 |
| Hard negative 高于正证据 | n/a | 越低越好 |
| Hop Recall | n/a | 仅知识检索可验证 hop |
| Path Success | n/a | 跨工具 hop 未接 Planner 时为 n/a |
| Constraint Recall | n/a | 未接 Planner/trace 时为 n/a |
| Pre-fusion information-need coverage | n/a | 子查询候选池覆盖率 |
| Post-fusion information-need coverage | n/a | 最终 Top-K 覆盖率 |
| Fusion information-need loss | n/a | 越低越好 |
| Partial: Available Evidence Recall | 0.500 | 只评价 KB 已有证据 |
| Partial: Information Need Coverage | 0.167 | 分母包含缺失 need |
| Partial: Missing Need Detection | n/a | 需要 Agent 最终回答 trace |
| Partial: False Complete Answer Rate | n/a | 越低越好；需要 Agent 最终回答 trace |
| Partial: Correct Escalation Rate | n/a | 需要 Agent 最终动作 trace |

门禁结论：**WARN**

未达标项：
- 仅包含 Partial Coverage 专项；未执行普通 Recall/MRR/nDCG 发布门禁

## 分桶指标

| 桶 | 数量 | Recall/拒答准确率 | MRR | NDCG | Graded nDCG | Evidence Recall | All-evidence | Hop Recall | Pre-need | Post-need |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| partial_coverage | 2 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

| query | Recall | Precision | MRR | NDCG | 召回文档 | 标注文档 |
|---|---|---|---|---|---|---|

## Partial Coverage 专项

裸检索只能验证已有证据召回和 information need 覆盖；缺失识别、假装完整回答和升级动作必须由端到端 Agent runner 评测。

| query | Available Evidence Recall | Information Need Coverage | 召回文档 |
|---|---:|---:|---|
| 去日本住民宿，想把粗陶茶具装进行李带过去，有什么要提前留意的？ | 1.00 | 0.33 | home-living.md,eval-home-living-概览.md,eval-home-living-避坑与合规.md |
| 想把竹木陶餐具寄给澳洲的朋友，寄出前该确认什么？ | 0.00 | 0.00 | eval-kitchen-dining-参数判断.md,eval-kitchen-dining-避坑与合规.md,eval-home-living-参数判断.md |


## 执行证据

- 选集：`all`，2/2 条；完整选集：True。
- 选集内容 SHA-256：`fdf2185413cd973d26bc8313073ef2043cc9031486955400861b1974a2644b6f`。
- 工作区内容 SHA-256：`bb6affe72c6791ca27bd8cfdcb00940012a23a25c233977dc64d48481c8b0ae5`（包含未提交源文件；详细范围见同名 manifest）。
- 执行状态：**COMPLETED**；门禁：**WARN**；门禁范围：`diagnostic`。
- 实际策略：`["legacy"]`。
- 模型、Prompt、数据文件、依赖版本及逐项 hash 均保存在同名 `.manifest.json`。
