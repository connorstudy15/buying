# Knowledge Eval v5

本版本把“证据覆盖程度”和“缺失原因”拆成两个正交字段，避免把 Partial Coverage、
Unanswerable 和 Knowledge Gap 塞进同一个互斥 query type。

## 数据集

- `knowledge_eval_core_61.jsonl`：当前可用的正式集合；50 条 complete、11 条 none。
- `knowledge_eval_partial_coverage_2.jsonl`：`v4-044`、`v4-047`，已有部分证据但缺当前外部权威证据。
- `knowledge_eval_knowledge_gap_4.jsonl`：问题合理但 KB 缺知识，不进入普通 Recall 门禁。
- `MANIFEST.json`：输入及三份输出的 SHA-256、数量和人工裁决摘要。

完整字段和计分规则见 `COVERAGE_CONTRACT.md`。

## 当前 runner 能测什么

`scripts/eval/run_category_recall.py` 当前真实计算：

- complete：普通 Recall/MRR/nDCG、Evidence Recall、All-Evidence Recall；
- partial：Available Evidence Recall、Information Need Coverage；
- none：不可回答准确率。

Missing Need Detection、False Complete Answer Rate、Correct Escalation Rate 需要 Agent 最终回答/动作 trace，
当前裸检索 runner 明确报告 `n/a`，不能把“召回为空”冒充“Agent 已识别缺失”。

## 重建

```powershell
.venv\Scripts\python.exe scripts\eval\build_knowledge_v5_coverage_sets.py
```

脚本只读取 v4 审核产物和独立盲审结果，不修改已冻结的 v3 文件。
