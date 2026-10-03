# 8 题独立证据盲审报告

审计日期：2026-10-03。阶段 A 先固定 Query 的必要需求并落盘，阶段 B 才查阅知识库正文、清单和标注定义。正证据阈值为 `grade >= 2`。知识清单标明当前资料为合成演示快照，政策与航司规定只用于识别核验边界。

## 最终决策

| ID | 必要需求覆盖 | 可回答性 | 评测去留 | 置信度 |
|---|---:|---|---|---:|
| v4-044 | 1/3 | UNANSWERABLE | MOVE_TO_UNANSWERABLE_SUBSET | 0.87 |
| v4-045 | 0/2 | UNANSWERABLE | MOVE_TO_UNANSWERABLE_SUBSET | 0.92 |
| v4-047 | 1/3 | UNANSWERABLE | MOVE_TO_UNANSWERABLE_SUBSET | 0.90 |
| v4-060 | 2/2 | ANSWERABLE | KEEP_FULL | 0.90 |
| v4-r009 | 2/2 | ANSWERABLE | KEEP_FULL | 0.82 |
| v4-r011 | 1/2 | UNANSWERABLE | MOVE_TO_KNOWLEDGE_GAP_SUBSET | 0.89 |
| v4-r012 | 1/3 | UNANSWERABLE | MOVE_TO_KNOWLEDGE_GAP_SUBSET | 0.86 |
| v4-r014 | 0/3 | UNANSWERABLE | MOVE_TO_KNOWLEDGE_GAP_SUBSET | 0.81 |

**可回答性数量：** ANSWERABLE 2；CONDITIONAL 0；UNANSWERABLE 6。

**评测去留数量：** KEEP_FULL 2；KEEP_CONDITIONAL 0；MOVE_TO_UNANSWERABLE_SUBSET 3；MOVE_TO_KNOWLEDGE_GAP_SUBSET 3；REJECT_AMBIGUOUS 0。

## 各题必要需求与证据边界

### v4-044 粗陶茶具赴日本

- n1 已覆盖：`knowledge/home-living.md` 第 17、18、28 行支持核对茶具重量、收纳包与陶瓷加固包装。
- n2 未覆盖：`knowledge/travel-gear.md` 第 33 行只谈登机箱三边和；没有茶具的随身/托运规则。
- n3 未覆盖：`knowledge/eval-policy-jp.md` 第 4、92 行只提示演示资料及权威核验；没有个人茶具入境日本的具体边界或对应部门。必须核对日本现行海关/检疫要求、航司票价及行李限制。

### v4-045 折叠双肩包搭廉航

- n1 未覆盖：`knowledge/travel-gear.md` 第 11、18 行是品类容量与自重参考，缺装载后尺寸和重量。
- n2 未覆盖：同文件第 33 行只对登机箱提示航司差异，缺该廉航票价的免费随身件数、尺寸和重量。须查具体航司、航班、票价并量装满的包。

### v4-047 竹木陶餐具寄澳洲

- n1 已覆盖：`knowledge/home-living.md` 第 10、18、28 行支持木竹陶材质、陶质易碎与原厂加固包装。
- n2 未覆盖：`knowledge/cross-border-guide.md` 第 33 行仅有动植物制品的泛化提醒，不能推出澳洲对竹木成品的准入结论。须向澳大利亚主管机构核验现行生物安全和申报要求。
- n3 未覆盖：`knowledge/eval-policy-global-shipping.md` 第 23 行只要求按目的国核验配送，缺所选承运渠道的收寄、包装与申报要求。

### v4-060 演示电池说明与今日航司规定

- n1 已覆盖：`knowledge/eval-policy-battery.md` 第 4、41 行明确材料是演示快照，不能替代监管公告。
- n2 已覆盖：`knowledge/cross-border-guide.md` 第 32 行说明含电池灯具的航空限制需单独确认；`knowledge/eval-policy-battery.md` 第 92 行要求向实时或权威来源核验。知识库不能提供今日具体航司条款。
- 结论为 ANSWERABLE：题目只问演示资料能否当作最新规定，原文足以回答“不能”；实际携带须另按航司、航班和电池参数核验。

### v4-r009 竹木陶餐具快递包装

- n1 已覆盖：`knowledge/home-living.md` 第 10、18 行支持陶质部件的破损风险，不能据此声称竹木部件同样易碎。
- n2 已覆盖：同文件第 18、28 行支持核对原厂加固包装并提示易碎风险。答案应停留在这些有证据的包装要点，不能编造缓冲材料规格或破损概率。

### v4-r011 收纳袋耐用与合寄邮费

- n1 未覆盖：`knowledge/travel-gear.md` 第 5、19 行只是旅行装备的一般耐用性判断，没有对应收纳袋材质、缝线、拉链或循环使用依据。
- n2 已覆盖：`knowledge/cross-border-guide.md` 第 26 行明确体积重与实重取大值，第 25 行仅提供常见多件计费方式。具体邮费仍需目的地、承运商、包装后实重和尺寸。

### v4-r012 头灯雨天与含电池寄递

- n1 已覆盖通用判断框架：`knowledge/outdoor-sports.md` 第 17 行说明 IPX 防水等级与雨天建议；未给出指定头灯的等级。
- n2 未覆盖：同文件第 11 行只提可充电头灯，缺电池类型、容量和装配状态。
- n3 未覆盖：`knowledge/cross-border-guide.md` 第 32 行只提示含电池灯具跨境邮寄受限，缺包装、申报和承运细则。须查具体 SKU、目的国及承运商当前规则。

### v4-r014 飞机携露营灯用于沙滩

- n1 未覆盖：`knowledge/outdoor-sports.md` 第 9、17、33 行只涉及常见露营灯防水与磁吸挂钩边界，不能证明指定灯具防沙、耐盐雾或沙地稳定。
- n2 未覆盖：没有对应灯具的电池类型、Wh 容量或可拆卸状态。
- n3 未覆盖：`knowledge/cross-border-guide.md` 第 32 行只提示航空限制，缺随身/托运和该航司当前规则。须核对具体 SKU 及航班。

## 缺失证据与外部核验

- 商品证据：折叠包装载后尺寸重量；收纳袋反复使用依据；头灯 IP 与电池规格；露营灯防沙、耐盐雾、稳定性和电池规格。
- 运输证据：茶具随身/托运边界、廉航免费行李额、含电池头灯国际寄递包装申报、露营灯航空携带细则。
- 目的地与渠道证据：日本个人携茶具入境要求；澳大利亚竹木陶餐具生物安全/海关要求；相关国际承运商的当前收寄条款。
- 当前政策均须向对应航司、目的地主管机构或实际承运商核验。静态演示资料不能作为今天有效的政策结论；未查到原文不能被解释为准许或禁止。

## 低置信度题

- `v4-r009`（0.82）：原文只说“原厂加固包装”，足以支持一个有限包装建议；若评测要求缓冲、隔离、固定等具体操作，应移至知识缺口集合。
- `v4-r014`（0.81）：防水等级是局部线索，沙滩适用还涉及防沙、盐雾和放置稳定性；目前将整项环境需求判为未覆盖。

## 建议集合

- 稳定 Core：`v4-060`（演示资料不能充当最新规定）、`v4-r009`（答案限定为陶质风险与原厂加固包装）。
- 有条件专项：无。
- 不可回答专项：`v4-044`、`v4-045`、`v4-047`。
- 知识缺口集合：`v4-r011`、`v4-r012`、`v4-r014`。
- 删除：无。若 Core 要求逐步包装操作而非检查要点，`v4-r009` 需重新审定。

## 隔离声明

本次仅读取指定盲审 Query、`knowledge/*.md`、`knowledge/manifest.jsonl` 与 `eval/knowledge/v3/LABELING_CONTRACT.md`，以及本次生成的审计输出。没有读取禁用文件、旧逐题标签、实验结果或 Git 历史；没有联网，也没有运行 QueryProcessor。未修改仓库现有代码、知识文件、评测文件或历史标签。