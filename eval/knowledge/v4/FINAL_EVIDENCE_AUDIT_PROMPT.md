# 知识评测 8 题独立证据盲审提示词

你是独立的 RAG 知识评测审核员。请在本地仓库 `D:\globex-agent-main` 中审核指定的 8 道题。

本任务只判断：

1. 当前知识库是否有足够证据支持完整回答；
2. 每个必要信息需求是否都有独立证据；
3. 答案属于可直接回答、有条件回答，还是当前知识库不可回答；
4. 该题能否作为稳定的知识检索评测题。

不要评测当前检索器是否能命中，不要运行 QueryProcessor，不要根据已有标签猜答案。

## 一、严格盲审隔离

你只能读取：

- 盲审题目：`D:\globex-agent-main\eval\knowledge\v4\final_evidence_audit_blind_queries.jsonl`
- 知识库正文：`D:\globex-agent-main\knowledge\*.md`
- 知识库清单：`D:\globex-agent-main\knowledge\manifest.jsonl`
- 标注定义：`D:\globex-agent-main\eval\knowledge\v3\LABELING_CONTRACT.md`

严禁读取或搜索以下内容，即使文件就在本地：

- `stage_b_reviewed_labels.jsonl`
- `knowledge_eval_candidates.reviewed.jsonl`
- `human_review_increment.csv`
- `label_conflicts.jsonl`
- `stage_b_audit_report.md`
- `query_strategy_adjudication.jsonl`
- `QUERY_STRATEGY_ADJUDICATION.md`
- `candidate_pool*.jsonl`、`candidate_pool*.manifest.json`
- `blind_queries_approved.jsonl`、`blind_query_audit.jsonl`
- `eval/runs/**`
- 任何旧的逐题标签、命中结果、实验报告或审核结论
- Git 历史中的上述文件，包括 `git show`、`git diff`、`git blame` 或旧 commit 内容

不得联网搜索。我们评估的是“当前本地知识库能否支撑回答”，不是现实世界中能否从互联网找到答案。

## 二、必须分两阶段执行

### 阶段 A：只看 Query，不看知识正文

1. 只读取 `final_evidence_audit_blind_queries.jsonl`。
2. 对每题独立写出：
   - 用户真正想解决的最终问题；
   - 回答该问题必需的 `required_information_needs`；
   - 哪些只是可选补充，不应算作必需证据；
   - 每个必要需求为什么能够独立检索、独立成功或失败。
3. 立即把结果写入：
   `D:\globex-agent-main\eval\knowledge\v4\independent_evidence_audit\phase_a_needs.jsonl`
4. 阶段 A 文件写完后才能读取 `knowledge\*.md`。不得在查看正文后反向修改阶段 A 的必要需求。

阶段 A 每行结构：

```json
{
  "id": "...",
  "query": "...",
  "final_user_goal": "...",
  "required_information_needs": [
    {"need_id": "n1", "description": "...", "independent_failure_reason": "..."}
  ],
  "optional_information": ["..."],
  "phase": "blind_need_analysis"
}
```

### 阶段 B：直接检查知识库原文

阶段 A 完成后，才可读取 `knowledge\*.md`。必须直接在知识正文中搜索证据，不能使用现成候选池或现成标签。

对每个 `required_information_need`：

- 找出所有真正支持该需求的证据；
- 记录真实相对路径、Markdown 标题、准确连续原文和行号；
- 标记证据强度：
  - `3 = core`：可以直接支持该需求的核心结论；
  - `2 = supporting`：能够实质支持，但通常需要与其他证据组合；
  - `1 = topical_non_supporting`：主题相关，但不能支撑答案；
  - `0 = irrelevant`：无关；
- 明确说明证据能证明什么、不能证明什么；
- 不得把常识、模型记忆、推测或互联网事实当成本地知识库证据；
- 不得把“知识库没有写”解释成某个事实必然成立；
- 不得把静态、演示或示例资料冒充今天仍有效的航司、海关、税费或政策规定；
- 不得用一段只覆盖部分问题的证据宣称整题已经可回答。

## 三、答案可回答性定义

每题必须选择且只选择一个：

### `ANSWERABLE`

所有必需信息需求都有 `grade >= 2` 的本地原文证据，证据足以在不补充外部事实的情况下回答完整问题。

### `CONDITIONAL`

所有必要的“通用判断框架”都有 `grade >= 2` 的证据，但最终结论明确依赖用户尚未提供的变量，或依赖需要临时核验的当前外部信息。知识库能够准确告诉用户：已有结论是什么、还缺什么、应向哪个权威来源核验。

注意：不能因为证据不足就自动判为 `CONDITIONAL`。若连通用判断框架或某个必要信息需求都没有证据，应判为 `UNANSWERABLE`。

### `UNANSWERABLE`

至少一个必要信息需求没有 `grade >= 2` 的本地证据，或者问题要求实时库存、具体 SKU 未知参数、未来事实、当前政策结论，而知识库连可靠的判断边界或核验路径也无法提供。

## 四、证据完整性与评测题去留

每题还要给出：

- `need_coverage`：已被 `grade >= 2` 证据覆盖的必要需求数 / 必要需求总数；
- `all_needs_covered`：只有全部必要需求都有证据才为 `true`；
- `benchmark_decision`：
  - `KEEP_FULL`：证据完整，可作为普通可回答题；
  - `KEEP_CONDITIONAL`：有完整的判断框架和边界证据，适合作为有条件回答题；
  - `MOVE_TO_UNANSWERABLE_SUBSET`：正确目标是验证系统能否识别本地知识不足；
  - `MOVE_TO_KNOWLEDGE_GAP_SUBSET`：题目合理，但知识库缺关键内容，暂不进入普通 Recall 评分；
  - `REJECT_AMBIGUOUS`：问题本身无法形成稳定、可重复的判定口径。

验收原则：

1. 多需求题不能用“一篇大致相关文档”代替逐需求覆盖。
2. `ANSWERABLE` 与 `CONDITIONAL` 的每个必要需求都必须至少有一条 `grade >= 2` 的准确原文。
3. 需要“当前最新规定”的问题，静态说明只能证明核验边界，不能证明当前规定本身。
4. 商品属性必须来自对应商品或明确适用的品类规则，不能从相似商品类推。
5. 运输、包装、环境适用、政策限制是不同的信息需求时，应分别核验。
6. 不因为希望凑够评测题数量而放宽证据标准。

## 五、阶段 B 输出

把逐题结果写入：

`D:\globex-agent-main\eval\knowledge\v4\independent_evidence_audit\phase_b_evidence_audit.jsonl`

每行结构：

```json
{
  "id": "...",
  "query": "...",
  "required_information_needs": [
    {
      "need_id": "n1",
      "description": "...",
      "evidence": [
        {
          "source": "knowledge/xxx.md",
          "section": "Markdown 标题",
          "line_start": 1,
          "line_end": 2,
          "quote": "准确连续原文",
          "grade": 3,
          "supports": "这段原文具体支持什么",
          "does_not_support": "这段原文不能证明什么"
        }
      ],
      "covered": true
    }
  ],
  "need_coverage": "2/2",
  "all_needs_covered": true,
  "answerability": "ANSWERABLE|CONDITIONAL|UNANSWERABLE",
  "answerability_reason": "...",
  "missing_variables_or_external_checks": ["..."],
  "benchmark_decision": "KEEP_FULL|KEEP_CONDITIONAL|MOVE_TO_UNANSWERABLE_SUBSET|MOVE_TO_KNOWLEDGE_GAP_SUBSET|REJECT_AMBIGUOUS",
  "decision_reason": "...",
  "confidence": 0.0
}
```

另外生成中文报告：

`D:\globex-agent-main\eval\knowledge\v4\independent_evidence_audit\audit_report.md`

报告必须包含：

1. 8 题最终决策表；
2. 每题必要需求覆盖情况；
3. `ANSWERABLE / CONDITIONAL / UNANSWERABLE` 数量；
4. 各种 benchmark decision 数量；
5. 所有缺失证据和必须外部核验的内容；
6. 低于 `0.85` 置信度的题；
7. 建议进入稳定 Core、专项 subset、知识缺口集合或删除的 ID；
8. 明确声明没有读取禁用文件、历史标签、实验结果或 Git 历史。

## 六、机械自检

完成后自行检查：

- 阶段 A 和阶段 B 都恰好包含 8 个唯一 ID；
- 阶段 B 的必要需求与阶段 A 完全一致，不得事后改写；
- 每条引用的路径真实存在；
- 每段 quote 能在对应文件中逐字找到；
- 行号覆盖该 quote；
- grade 只能为 0、1、2、3；
- `all_needs_covered=true` 时，每个必要需求至少有一条 grade≥2 证据；
- `ANSWERABLE` 或 `CONDITIONAL` 时 `all_needs_covered` 必须为 true；
- 不修改仓库现有代码、知识文件、评测文件或历史标签，只能写入 `independent_evidence_audit` 输出目录。

发现不确定项时不要猜测，降低 confidence，并把问题写进报告供用户决定。
