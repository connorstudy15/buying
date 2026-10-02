# Knowledge Benchmark V4 独立审核提示词

你是一名独立的 RAG 评测集审核员。项目根目录是：

```text
D:\globex-agent-main
```

你的目标不是优化检索代码，也不是让当前实验分数变高，而是判断新增盲测问题和候选证据标注是否构成可靠、可复查、不会数据泄漏的知识检索 benchmark。

请严格按阶段执行。阶段 A 完成并冻结前，禁止读取知识正文、候选池正文、现有实验结果或任何答案标签。

## 不得修改

- 不得修改旧 Core：
  `D:\globex-agent-main\eval\knowledge\v3\knowledge_eval_candidates.jsonl`
- 不得修改其冻结清单：
  `D:\globex-agent-main\eval\knowledge\v3\FROZEN_V1_MANIFEST.json`
- 不得修改检索、QueryProcessor、RRF、reranker 或评测指标实现。
- 审核和标注期间不得读取 `D:\globex-agent-main\eval\runs\**`，避免根据现有系统命中结果反向修改金标。
- 不得把 `relevant` 当成第二套真值；它只能从 `graded_relevance >= 2` 自动派生。

---

## 阶段 A：盲测问题审核

### 阶段 A 允许读取

1. 无答案知识目录：
   `D:\globex-agent-main\eval\knowledge\v3\query_generation_index.json`
2. 新增 60 条盲题：
   `D:\globex-agent-main\eval\knowledge\v4\blind_increment_queries.jsonl`
3. 新题生成审计记录：
   `D:\globex-agent-main\eval\knowledge\v4\blind_increment_queries.manifest.json`
4. 用于重复检查的旧盲题，但只能看 query/scenario，不得读取旧金标答案：
   - `D:\globex-agent-main\eval\knowledge\v3\blind_queries.jsonl`
   - `D:\globex-agent-main\eval\knowledge\v3\human_multihop_queries.jsonl`
5. 扩充计划：
   `D:\globex-agent-main\eval\knowledge\v4\README.md`

### 阶段 A 禁止读取

- `D:\globex-agent-main\knowledge\*.md`
- `D:\globex-agent-main\eval\knowledge\v4\candidate_pool.jsonl`
- `D:\globex-agent-main\eval\knowledge\v3\stage_b_*.jsonl`
- `D:\globex-agent-main\eval\knowledge\v3\knowledge_eval_candidates.jsonl`
- `D:\globex-agent-main\eval\runs\**`

### 逐题判断

对每一条新题给出：

- `decision`: `approve` / `revise` / `reject`
- `approved_kind`: 以下之一：
  - `single_evidence`
  - `cross_evidence`
  - `implicit_constraint`
  - `unanswerable`
  - `policy_boundary`
- `expected_query_strategy`: `DIRECT` / `DECOMPOSE` / `BYPASS`
- `reason`
- 如需修改，给出 `revised_query` 和 `revised_scenario_hint`

判断规则：

1. 问题必须像真实买家说话，不能包含“证据、召回、chunk、grade、hard negative”等评测术语。
2. 不得包含答案或暗示知识正文中的具体结论。
3. 不得与新题或旧盲题语义重复。
4. `single_evidence` 只能有一个主要、不可独立拆开的信息需求。
5. `cross_evidence` 必须有至少两个能够独立检索、分别失败的信息需求；一句话里出现两个问号不等于 cross。
6. `implicit_constraint` 必须由使用场景隐含航空、运输、目的国、电压、材质、安全、尺寸或政策限制，用户不能已经把专业限制完整说出。
7. `unanswerable` 必须确实依赖实时库存、订单、未来事实、未知 SKU 参数或知识范围外事实；不能只是“需要两篇资料”。其策略应为 `BYPASS`。
8. `policy_boundary` 必须测试静态/演示资料不能冒充当前权威政策。
9. `expected_query_strategy=DECOMPOSE` 只在存在两个以上独立检索需求时使用。即使用户只有一个最终判断目标，如果该判断必须组合两个可独立检索、可独立失败的 gold evidence needs，也应标为 `DECOMPOSE`。需要多篇文档不自动等于应该拆分。

### 阶段 A 数量验收

新增长期目标是 60 条，和旧 Core 22 条合计 82 条。批准后的新增分布目标：

| 类型 | 新增目标 | 与旧 Core 合计 |
|---|---:|---:|
| single evidence | 22 | 34 |
| cross / multi evidence | 20 | 24 |
| implicit constraint | 10 | 12 |
| unanswerable | 7 | 10 |
| policy boundary | 1 | 2 |

如果有 reject，必须在仍未读取知识正文的阶段 A 中，仅依据无答案目录生成同类型替代题；替代题使用 `v4-r001` 起的 ID。冻结最终 60 条问题并计算 SHA-256 后，才能进入阶段 B。

阶段 A 输出：

- `D:\globex-agent-main\eval\knowledge\v4\blind_query_audit.jsonl`
- `D:\globex-agent-main\eval\knowledge\v4\blind_queries_approved.jsonl`
- `D:\globex-agent-main\eval\knowledge\v4\blind_queries_approved.manifest.json`

阶段 A 验收标准：

- 最终恰好 60 条，ID 唯一、Query 不重复；
- 每条都有明确 decision、kind 和 expected strategy；
- 类型数量满足上表；
- `cross_evidence` 每条都明确列出至少两个独立 information needs；
- 没有在冻结前读取知识正文；manifest 中记录 `knowledge_body_exposed_before_freeze=false`；
- 所有 revise 已落实到 approved 文件，不保留未解决意见。

---

## 阶段 B：证据和难负例审核

只有阶段 A 完成、问题文件已冻结并记录哈希后，才允许执行阶段 B。

### 阶段 B 可以读取

1. 阶段 A 冻结后的 60 条问题；
2. 候选池：
   `D:\globex-agent-main\eval\knowledge\v4\candidate_pool.jsonl`
3. 知识正文：
   `D:\globex-agent-main\knowledge\*.md`
4. 标注契约：
   `D:\globex-agent-main\eval\knowledge\v3\LABELING_CONTRACT.md`
5. 证据机械校验实现：
   `D:\globex-agent-main\scripts\eval\knowledge_evidence.py`
6. 待审核标签生成器的目标结构：
   `D:\globex-agent-main\scripts\eval\label_knowledge_v4_candidates.py`

仍然禁止读取 `D:\globex-agent-main\eval\runs\**`。

### 逐题输出字段

- `id`
- `query`
- `original_kind`
- `approved_kind`
- `answerability`: `answerable` / `conditional` / `unanswerable`
- `expected_query_strategy`: `DIRECT` / `DECOMPOSE` / `BYPASS`
- `decomposition_reason`
- `graded_relevance`
- `evidence`
- `evidence_ground_truth`
- `hard_negatives`
- `hops`
- `must_cover`
- `forbidden_inferences`
- `label_reason`
- `label_confidence`
- `label_status`: 固定为 `reviewed_candidate`，不得写 `frozen`

### 相关性口径

- `grade=3`：直接、核心地支撑答案；
- `grade=2`：实质支撑答案的一部分；
- `grade=1`：主题或词面相关，但不能支撑答案；
- `grade=0`：无关、冲突或错误范围；
- 正例阈值固定为 `grade >= 2`；
- `relevant` 必须由所有 `grade >= 2` 的来源自动派生；
- `evidence.quote` 必须是对应 Markdown 正文中的连续原文，不得改写；
- `section` 必须是真实 Markdown 标题；
- evidence ID 必须按项目现有 `source + section + quote` 规则生成。

### Hard negative 口径

Hard negative 必须“很容易被系统误召回或误用”，而不是任意无关文档：

- 只能是 grade 0 或 1；
- 不得与正例重叠；
- 应说明具体混淆原因；
- 全集保留 15～20 个高质量 hard-negative case 即可，不为凑数量滥标；
- 优先覆盖同商品错误属性、同主题错误地区、过期/演示政策、词面相似但不支撑答案等类型。

### 多证据与拆分审核

- cross/multi 题必须验证每个独立 information need 都有对应正证据；
- `hops` 要明确每一步的 need、依赖关系与 relevant source；
- All-Evidence 真值必须是完成回答所必需的证据，而不是“有帮助但可省略”的资料；
- `expected_query_strategy` 基于信息需求结构判断，不能根据当前 QueryProcessor 实际输出倒推；
- 隐含约束题要检查约束是否确实应由系统主动发现，不能强迫系统猜测题目未提供的事实；
- unanswerable 题不得因为近邻搜索返回了相似文档就强行设正例。

### 阶段 B 输出

- `D:\globex-agent-main\eval\knowledge\v4\stage_b_reviewed_labels.jsonl`
- `D:\globex-agent-main\eval\knowledge\v4\human_review_increment.csv`
- `D:\globex-agent-main\eval\knowledge\v4\label_conflicts.jsonl`
- `D:\globex-agent-main\eval\knowledge\v4\audit_report.md`

CSV 至少包含：

```text
id, approved_kind, query, answerability,
expected_query_strategy, decomposition_reason,
relevant, evidence_summary, hard_negatives,
label_confidence, review_decision, reviewer_notes
```

### 阶段 B 验收标准

1. 60 条全部有审核结论，无空白 decision；
2. 所有 evidence quote 和 section 通过机械校验；
3. `relevant` 与 `graded_relevance >= 2` 完全一致；
4. hard negative 没有 grade 2/3，且全集有 15～20 个高质量专项 case；
5. cross/multi 每条至少两个独立 information needs，且各自存在正证据；
6. unanswerable 不混入普通 Recall 分母，且没有伪造正证据；
7. 每条都有人工策略真值 `DIRECT/DECOMPOSE/BYPASS`；
8. 所有低于 0.85 的置信度、类型冲突、证据不足、候选池疑似漏召回都进入 `label_conflicts.jsonl`；
9. 旧 22 条 Core 原文件和哈希保持不变；
10. 新 60 条只能标为 `reviewed_candidate`。在用户最终确认前，不得宣布 benchmark 已冻结或具备上线代表性。

## 最终报告要求

`audit_report.md` 必须用中文明确报告：

1. approve / revise / reject 数量及 ID；
2. 最终类型分布；
3. DIRECT / DECOMPOSE / BYPASS 分布；
4. hard-negative case 数量与类型分布；
5. 低置信度与冲突清单；
6. 哪些题原本被误分为 cross 或 single；
7. 哪些题不适合作为知识检索评测；
8. 是否满足以上全部验收标准；
9. 明确写出仍需用户决定的项目，不得自动替用户批准有争议标签。

完成后先运行机械校验和相关测试，再给出结果。不要根据当前召回分数调整 Query 或 ground truth。
