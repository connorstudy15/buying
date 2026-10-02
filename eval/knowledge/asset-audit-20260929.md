# 知识召回评测资产审计（2026-09-29）

## 已冻结的实验底座

- 知识文档：45 篇 Markdown，共 245,300 bytes、92,734 字符。
- 当前切块结果：151 个 chunk。
- 语料指纹：`382c697acf0987e8fb93c40df1d65347cd5bd9aa5194570bcb3750140bcdc758`。
- 切块策略：`TextParser` + `ApproxTokenChunker(chunk_size=512, overlap=50)`。
- 检索策略：稠密向量候选深度 `min(80, top_k * 8)`，标题/地域定向补召回，按文档去重后返回 Top-K。
- 当前运行配置：`qwen3.7-text-embedding-flash`、1024 维、本地嵌入式 Qdrant、collection `globex_category_kb`。

完整逐文档哈希、chunk 数、元数据和评测集哈希见 `corpus-snapshot-20260929.json`。

## 保留的回归集

1. `eval/v1/knowledge_retrieval.jsonl`：50 条（dev 35 / release 15），包含 single 20、cross 15、unanswerable 10、conflict_or_expired 5。
2. `eval/category_recall.jsonl`：旧版 22 条，继续保留作历史回归子集。

两套旧集目前都是“文档文件名”粒度金标，没有 evidence span、graded relevance、hard negative 或人工审批记录。因此它们适合防止明显回退，但不足以单独判断父子块是否真正找到了正确证据段。

## 零成本预检

现有 runner 已用 `--dry-run` 完整选中正式 50 条：dev 35、release 15，无缺失；状态为 `NOT_RUN`，未调用 Embedding/Qdrant，也没有生成虚假的通过结论。预检证据位于 `eval/knowledge/preflight/`。

## Baseline 前置条件

当前 Embedding 复用 LLM 网关配置。此前真实连通测试返回过 403，因此在重新验证 Embedding 接口可用前，不应把 keyword fallback 或失败结果当作向量 baseline。

有效 baseline 应固定本快照指纹，分别报告 dev/release 与四个桶的 Recall@3、MRR@3、nDCG@3、不可回答准确率、政策拒答准确率和延迟分位数。父子块实验必须复用同一语料版本、同一 Query、同一 Embedding 模型和同一 K，只改变切块与返回证据方式。
