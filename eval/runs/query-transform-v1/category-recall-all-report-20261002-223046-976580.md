# 品类知识库召回评测报告（2026-10-02 22:31:22）

标注集 `eval\knowledge\v3\knowledge_eval_candidates.jsonl`，正例 19 条。兼容文档级指标；存在 evidence_ground_truth 时同时按原文证据评分。

| 指标 | 值 | 阈值 |
|---|---|---|
| Recall@3 | 0.658 | ≥ 0.75（阻断） |
| Precision@3 | 0.281 | ≥ 0.45（阻断） |
| MRR | 0.763 | ≥ 0.65（阻断） |
| NDCG@3 | 0.709 | ≥ 0.7（阻断） |
| Graded nDCG@3 | 0.683 | 0–3 级相关性，观察项 |
| 不可回答准确率 | 0.000 | 未启用 |
| 政策拒答准确率 | 1.000 | 未启用 |
| Evidence Recall | 0.553 | 观察项 |
| All-evidence Recall | 0.421 | 观察项 |
| Hard-negative hit rate | 0.421 | 越低越好 |
| Hard negative 高于正证据 | 0.158 | 越低越好 |
| Hop Recall | 0.000 | 仅知识检索可验证 hop |
| Path Success | n/a | 跨工具 hop 未接 Planner 时为 n/a |
| Constraint Recall | n/a | 未接 Planner/trace 时为 n/a |
| Pre-fusion information-need coverage | 0.842 | 子查询候选池覆盖率 |
| Post-fusion information-need coverage | 0.474 | 最终 Top-K 覆盖率 |
| Fusion information-need loss | 0.368 | 越低越好 |

门禁结论：**BLOCK**

未达标项：
- Recall@3 0.6579 < 0.75
- Precision@3 0.2807 < 0.45

## 分桶指标

| 桶 | 数量 | Recall/拒答准确率 | MRR | NDCG | Graded nDCG | Evidence Recall | All-evidence | Hop Recall | Pre-need | Post-need |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cross_evidence | 4 | 0.417 | 0.625 | 0.520 | 0.470 | 0.500 | 0.250 | n/a | 0.750 | 0.500 |
| implicit_constraint_multi_hop | 2 | 0.750 | 1.000 | 0.880 | 0.789 | 0.500 | 0.000 | 0.000 | 0.500 | 0.000 |
| policy_boundary | 1 | 0.333 | 1.000 | 0.630 | 0.734 | 0.000 | 0.000 | n/a | 0.000 | 0.000 |
| single_evidence | 12 | 0.750 | 0.750 | 0.750 | 0.731 | 0.625 | 0.583 | n/a | 1.000 | 0.583 |
| unanswerable | 3 | 0.000 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

| query | Recall | Precision | MRR | NDCG | 召回文档 | 标注文档 |
|---|---|---|---|---|---|---|
| 我想买个能带上飞机的登机箱，20寸那种，一般得看哪些航司尺寸要求啊？ | 1.00 | 0.33 | 1.00 | 1.00 | travel-gear.md,eval-travel-gear-避坑与合规.md,eval-travel-gear-参数判断.md | travel-gear.md |
| 折叠双肩包平时塞行李箱里备用，材质选哪种更耐造一点？ | 1.00 | 0.33 | 1.00 | 1.00 | travel-gear.md,eval-travel-gear-参数判断.md,eval-travel-gear-概览.md | travel-gear.md |
| 旅行三件套收纳起来到底省不省地方，适合小箱子吗？ | 0.00 | 0.00 | 0.00 | 0.00 | eval-travel-gear-价格与预算.md,eval-travel-gear-避坑与合规.md,eval-travel-gear-概览.md | travel-gear.md |
| 收纳用品如果买一套，重量上会不会给行李增加很多负担？ | 0.00 | 0.00 | 0.00 | 0.00 | eval-travel-gear-避坑与合规.md,eval-travel-gear-价格与预算.md,eval-travel-gear-概览.md | travel-gear.md |
| 氮化镓充电器多口同时用的时候，功率是怎么分配的？ | 1.00 | 0.33 | 1.00 | 1.00 | digital-accessories.md,eval-digital-accessories-概览.md,eval-digital-accessories-避坑与合规.md | digital-accessories.md |
| 移动电源带出门坐飞机，锂电池运输这块一般有什么讲究？ | 0.50 | 0.33 | 0.50 | 0.48 | eval-policy-battery.md,digital-accessories.md,eval-digital-accessories-避坑与合规.md | digital-accessories.md,cross-border-guide.md |
| 降噪耳机在地铁里用，降噪效果主要看哪些方面？ | 1.00 | 0.33 | 1.00 | 1.00 | digital-accessories.md,eval-digital-accessories-参数判断.md,eval-beauty-care-参数判断.md | digital-accessories.md |
| 磁吸无线充跟不同手机壳、机型兼容性怎么样？ | 1.00 | 0.33 | 1.00 | 1.00 | digital-accessories.md,eval-digital-accessories-避坑与合规.md,eval-office-study-避坑与合规.md | digital-accessories.md |
| 粗陶茶具寄快递容易碎，包装上该怎么注意？ | 1.00 | 0.33 | 1.00 | 1.00 | home-living.md,eval-home-living-避坑与合规.md,eval-home-living-参数判断.md | home-living.md |
| 竹木陶餐具直接接触吃的，食品接触安全这块怎么看？ | 0.00 | 0.00 | 0.00 | 0.00 | eval-kitchen-dining-避坑与合规.md,eval-kitchen-dining-参数判断.md,eval-kitchen-dining-概览.md | home-living.md |
| 露营灯亮度怎么看，晚上在帐篷边够不够用？ | 1.00 | 0.33 | 1.00 | 1.00 | outdoor-sports.md,eval-office-study-避坑与合规.md,eval-office-study-价格与预算.md | outdoor-sports.md |
| 头灯续航如果开强光，一般能撑多久？ | 1.00 | 0.33 | 1.00 | 1.00 | outdoor-sports.md,eval-office-study-概览.md,eval-office-study-价格与预算.md | outdoor-sports.md |
| 折叠登山杖收起来有多长，能塞进登机箱吗？ | 1.00 | 0.33 | 1.00 | 1.00 | outdoor-sports.md,eval-travel-gear-价格与预算.md,travel-gear.md | outdoor-sports.md |
| 我打算带20寸登机箱，还想把移动电源放里面上飞机，箱子尺寸和电池运输这两块是不是都得管？ | 0.67 | 0.67 | 1.00 | 0.84 | travel-gear.md,eval-travel-gear-避坑与合规.md,digital-accessories.md | travel-gear.md,digital-accessories.md,cross-border-guide.md |
| 我买了一套粗陶茶具想寄到国外送人，包装和运费体积重是不是都要先弄清楚？ | 0.00 | 0.00 | 0.00 | 0.00 | eval-home-living-避坑与合规.md,eval-kitchen-dining-避坑与合规.md,eval-travel-gear-参数判断.md | home-living.md,cross-border-guide.md |
| 磁吸无线充带到国外用，电器电压和手机兼容性是不是都得确认？ | 0.50 | 0.33 | 1.00 | 0.76 | digital-accessories.md,eval-digital-accessories-避坑与合规.md,eval-office-study-避坑与合规.md | digital-accessories.md,cross-border-guide.md |
| 我在网上翻到一份演示用的地区政策资料，版本好像是旧的，我能拿它当现在海关政策的权威结论吗？ | 0.33 | 0.33 | 1.00 | 0.63 | eval-policy-us.md,eval-policy-battery.md,eval-policy-material.md | eval-policy-us.md,eval-policy-eu.md,eval-policy-cn.md |
| 我要买个充电宝带着飞日本 | 0.50 | 0.33 | 1.00 | 0.76 | digital-accessories.md,eval-digital-accessories-避坑与合规.md,eval-travel-gear-避坑与合规.md | digital-accessories.md,cross-border-guide.md |
| 我想买个登机箱，再配一个折叠背包带上任意航空公司的飞机 | 1.00 | 0.33 | 1.00 | 1.00 | travel-gear.md,eval-travel-gear-避坑与合规.md,eval-travel-gear-价格与预算.md | travel-gear.md |


## 执行证据

- 选集：`all`，22/22 条；完整选集：True。
- 选集内容 SHA-256：`95724ce00a698e5bbd1751a1c4fd8deaac0238509a13898380f60635b157eabe`。
- 工作区内容 SHA-256：`850592f589041008b8b760ab8ec304005c3fedf6f3c741ae46a7fd36f29c06b9`（包含未提交源文件；详细范围见同名 manifest）。
- 执行状态：**COMPLETED**；门禁：**BLOCK**；门禁范围：`diagnostic`。
- 实际策略：`["query_transform_rrf"]`。
- 模型、Prompt、数据文件、依赖版本及逐项 hash 均保存在同名 `.manifest.json`。
