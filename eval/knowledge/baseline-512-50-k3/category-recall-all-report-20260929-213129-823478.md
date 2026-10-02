# 品类知识库召回评测报告（2026-09-29 21:31:36）

标注集 `eval\v1\knowledge_retrieval.jsonl`，正例 40 条。标注单位为知识文档名。

| 指标 | 值 | 阈值 |
|---|---|---|
| Recall@3 | 0.875 | ≥ 0.85（阻断） |
| Precision@3 | 0.417 | 观察项（未穷举金标，不阻断） |
| MRR | 0.875 | ≥ 0.85（阻断） |
| NDCG@3 | 0.875 | ≥ 0.85（阻断） |
| 不可回答准确率 | 1.000 | ≥ 1.0（阻断） |
| 政策拒答准确率 | 0.000 | ≥ 1.0（阻断） |

门禁结论：**BLOCK**

未达标项：
- 政策拒答准确率 0.0 < 1.0

| query | Recall | Precision | MRR | NDCG | 召回文档 | 标注文档 |
|---|---|---|---|---|---|---|
| 选购数码配件时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | digital-accessories.md,eval-digital-accessories-避坑与合规.md,eval-digital-accessories-价格与预算.md | digital-accessories.md |
| 选购家居生活时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | home-living.md,eval-home-living-避坑与合规.md,eval-home-living-参数判断.md | home-living.md |
| 选购户外运动时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | outdoor-sports.md,eval-outdoor-sports-避坑与合规.md,eval-outdoor-sports-参数判断.md | outdoor-sports.md |
| 选购旅行装备时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | travel-gear.md,eval-travel-gear-避坑与合规.md,eval-travel-gear-参数判断.md | travel-gear.md |
| 选购旅行装备 概览时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-travel-gear-概览.md,eval-travel-gear-避坑与合规.md,eval-travel-gear-参数判断.md | eval-travel-gear-概览.md |
| 选购旅行装备 避坑与合规时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-travel-gear-避坑与合规.md,eval-travel-gear-价格与预算.md,eval-beauty-care-避坑与合规.md | eval-travel-gear-避坑与合规.md |
| 选购数码配件 概览时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-digital-accessories-概览.md,eval-digital-accessories-避坑与合规.md,eval-digital-accessories-价格与预算.md | eval-digital-accessories-概览.md |
| 选购数码配件 参数判断时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-digital-accessories-参数判断.md,eval-digital-accessories-避坑与合规.md,eval-digital-accessories-概览.md | eval-digital-accessories-参数判断.md |
| 选购数码配件 价格与预算时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-digital-accessories-价格与预算.md,eval-digital-accessories-避坑与合规.md,eval-travel-gear-价格与预算.md | eval-digital-accessories-价格与预算.md |
| 选购数码配件 避坑与合规时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-digital-accessories-避坑与合规.md,eval-travel-gear-避坑与合规.md,eval-digital-accessories-概览.md | eval-digital-accessories-避坑与合规.md |
| 选购家居生活 概览时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-home-living-概览.md,eval-home-living-避坑与合规.md,eval-home-living-参数判断.md | eval-home-living-概览.md |
| 选购家居生活 参数判断时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-home-living-参数判断.md,eval-travel-gear-参数判断.md,eval-office-study-参数判断.md | eval-home-living-参数判断.md |
| 选购家居生活 价格与预算时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-home-living-价格与预算.md,eval-travel-gear-价格与预算.md,eval-baby-pet-价格与预算.md | eval-home-living-价格与预算.md |
| 选购户外运动 价格与预算时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-outdoor-sports-价格与预算.md,eval-outdoor-sports-参数判断.md,eval-travel-gear-价格与预算.md | eval-outdoor-sports-价格与预算.md |
| 选购旅行装备 参数判断时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-travel-gear-参数判断.md,eval-travel-gear-避坑与合规.md,eval-travel-gear-价格与预算.md | eval-travel-gear-参数判断.md |
| 选购旅行装备 价格与预算时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-travel-gear-价格与预算.md,eval-travel-gear-参数判断.md,eval-travel-gear-避坑与合规.md | eval-travel-gear-价格与预算.md |
| 选购家居生活 避坑与合规时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-home-living-避坑与合规.md,eval-travel-gear-避坑与合规.md,eval-baby-pet-避坑与合规.md | eval-home-living-避坑与合规.md |
| 选购户外运动 概览时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-outdoor-sports-概览.md,eval-outdoor-sports-避坑与合规.md,eval-outdoor-sports-参数判断.md | eval-outdoor-sports-概览.md |
| 选购户外运动 参数判断时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-outdoor-sports-参数判断.md,eval-outdoor-sports-价格与预算.md,eval-outdoor-sports-避坑与合规.md | eval-outdoor-sports-参数判断.md |
| 选购户外运动 避坑与合规时，应该优先核对哪些可验证字段？ | 1.00 | 0.33 | 1.00 | 1.00 | eval-outdoor-sports-避坑与合规.md,eval-travel-gear-避坑与合规.md,eval-outdoor-sports-价格与预算.md | eval-outdoor-sports-避坑与合规.md |
| 同时比较数码配件和家居生活 价格与预算时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | digital-accessories.md,eval-home-living-价格与预算.md,eval-digital-accessories-价格与预算.md | digital-accessories.md,eval-home-living-价格与预算.md |
| 同时比较家居生活和户外运动 价格与预算时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | home-living.md,eval-outdoor-sports-价格与预算.md,eval-home-living-价格与预算.md | home-living.md,eval-outdoor-sports-价格与预算.md |
| 同时比较户外运动和美妆个护 价格与预算时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | outdoor-sports.md,eval-beauty-care-价格与预算.md,eval-outdoor-sports-价格与预算.md | outdoor-sports.md,eval-beauty-care-价格与预算.md |
| 同时比较旅行装备和厨房餐饮 概览时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | travel-gear.md,eval-kitchen-dining-概览.md,eval-kitchen-dining-价格与预算.md | travel-gear.md,eval-kitchen-dining-概览.md |
| 同时比较旅行装备 概览和厨房餐饮 避坑与合规时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | eval-travel-gear-概览.md,eval-kitchen-dining-避坑与合规.md,eval-travel-gear-避坑与合规.md | eval-travel-gear-概览.md,eval-kitchen-dining-避坑与合规.md |
| 同时比较旅行装备 避坑与合规和办公学习 概览时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | eval-travel-gear-避坑与合规.md,eval-office-study-概览.md,eval-office-study-避坑与合规.md | eval-travel-gear-避坑与合规.md,eval-office-study-概览.md |
| 同时比较数码配件 概览和办公学习 参数判断时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | eval-digital-accessories-概览.md,eval-office-study-参数判断.md,eval-digital-accessories-参数判断.md | eval-digital-accessories-概览.md,eval-office-study-参数判断.md |
| 同时比较数码配件 参数判断和办公学习 价格与预算时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | eval-digital-accessories-参数判断.md,eval-office-study-价格与预算.md,eval-digital-accessories-价格与预算.md | eval-digital-accessories-参数判断.md,eval-office-study-价格与预算.md |
| 同时比较数码配件 价格与预算和办公学习 避坑与合规时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | eval-digital-accessories-价格与预算.md,eval-office-study-避坑与合规.md,eval-office-study-价格与预算.md | eval-digital-accessories-价格与预算.md,eval-office-study-避坑与合规.md |
| 同时比较数码配件 避坑与合规和母婴宠物 概览时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | eval-digital-accessories-避坑与合规.md,eval-baby-pet-概览.md,eval-baby-pet-避坑与合规.md | eval-digital-accessories-避坑与合规.md,eval-baby-pet-概览.md |
| 同时比较旅行装备 参数判断和户外运动 避坑与合规时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | eval-travel-gear-参数判断.md,eval-outdoor-sports-避坑与合规.md,eval-outdoor-sports-参数判断.md | eval-travel-gear-参数判断.md,eval-outdoor-sports-避坑与合规.md |
| 同时比较旅行装备 价格与预算和美妆个护 概览时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | eval-travel-gear-价格与预算.md,eval-beauty-care-概览.md,eval-beauty-care-价格与预算.md | eval-travel-gear-价格与预算.md,eval-beauty-care-概览.md |
| 同时比较家居生活 避坑与合规和美妆个护 参数判断时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | eval-home-living-避坑与合规.md,eval-beauty-care-参数判断.md,eval-beauty-care-避坑与合规.md | eval-home-living-避坑与合规.md,eval-beauty-care-参数判断.md |
| 同时比较户外运动 概览和美妆个护 避坑与合规时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | eval-outdoor-sports-概览.md,eval-beauty-care-避坑与合规.md,eval-outdoor-sports-避坑与合规.md | eval-outdoor-sports-概览.md,eval-beauty-care-避坑与合规.md |
| 同时比较户外运动 参数判断和厨房餐饮 参数判断时，哪些证据不能只凭标题判断？ | 1.00 | 0.67 | 1.00 | 1.00 | eval-outdoor-sports-参数判断.md,eval-kitchen-dining-参数判断.md,eval-kitchen-dining-价格与预算.md | eval-outdoor-sports-参数判断.md,eval-kitchen-dining-参数判断.md |
| GLOBAL 的政策快照若没有权威来源或已经超过有效期，还能当作确定事实回答吗？ | 0.00 | 0.00 | 0.00 | 0.00 | （空） | cross-border-guide.md |
| EU 的政策快照若没有权威来源或已经超过有效期，还能当作确定事实回答吗？ | 0.00 | 0.00 | 0.00 | 0.00 | （空） | eval-policy-eu.md |
| JP 的政策快照若没有权威来源或已经超过有效期，还能当作确定事实回答吗？ | 0.00 | 0.00 | 0.00 | 0.00 | （空） | eval-policy-jp.md |
| SG 的政策快照若没有权威来源或已经超过有效期，还能当作确定事实回答吗？ | 0.00 | 0.00 | 0.00 | 0.00 | （空） | eval-policy-sg.md |
| US 的政策快照若没有权威来源或已经超过有效期，还能当作确定事实回答吗？ | 0.00 | 0.00 | 0.00 | 0.00 | （空） | eval-policy-us.md |


## 执行证据

- 选集：`all`，50/50 条；完整选集：True。
- 选集内容 SHA-256：`a118ec3ac4aa791abe629cf6f38e900f30ecc83853bd1f69eca028dc99fa4cc2`。
- 工作区内容 SHA-256：`d34d3ce3edcb465a758adfff204b1980d5c46de979f48433ade696fde09448ee`（包含未提交源文件；详细范围见同名 manifest）。
- 执行状态：**COMPLETED**；门禁：**BLOCK**；门禁范围：`diagnostic`。
- 实际策略：`["category_vector_document_scope_v1"]`。
- 模型、Prompt、数据文件、依赖版本及逐项 hash 均保存在同名 `.manifest.json`。
