# Knowledge Corpus Provenance Audit

本报告只读分析现有 collection；未删除文档、未重建索引、未修改 Candidate B。

## 结论

当前 `globex_category_kb` 不是生产知识与评测知识隔离后的 production corpus。
45 篇源文档全部声明为 `synthetic_evaluation_fixture`；40 篇 `eval-*` 文档贡献了 142/151 个 chunk。
这些文档是为了建立可区分的召回 baseline 而有意加入的评测困难候选，但运行时也通过同一个 `knowledge/*.md` glob 加载它们。
因此它们在评测语境中属于合法的 synthetic hard-negative/decoy corpus，在应用运行语境中构成 evaluation fixture pollution。

## 数量

- 总文档：45；总 chunk：151。
- synthetic/eval fixture：151 chunks（100.00%）。
- `eval-*`：40 documents / 142 chunks。
- 非 `eval-*`：5 documents / 9 chunks，但 metadata 仍全部是 synthetic fixture。
- 可按 metadata 认定的 production knowledge：0 documents / 0 chunks。

## 入库原因

- `app/infrastructure/rag/category_knowledge.py` 对 `knowledge/*.md` 无差别遍历并写入 collection，没有 source_type 或文件名前缀过滤。
- `app/composition.py` 在应用启动时调用同一个 bootstrap，因此不是只有 eval runner 才会加载这些文档。
- `tests/test_knowledge_fixture.py` 明确要求文档数 >=40、chunk 数 150–250，以让召回测试具有区分度。
- 所有 45 篇文档在 commit `8d824d8`（`chore: establish pre-query-planner baseline`）中一起加入。

## 重复模板

检测到 18 个跨文档模板组，共覆盖 142 个 chunk membership。
- `category-template::价格与预算::chunk-0`：8 chunks；文本相似均值 0.904；向量 cosine 均值 0.734；判断 `low_independence_template_repetition`。
- `category-template::价格与预算::chunk-1`：8 chunks；文本相似均值 0.869；向量 cosine 均值 0.826；判断 `low_independence_template_repetition`。
- `category-template::价格与预算::chunk-2`：8 chunks；文本相似均值 0.837；向量 cosine 均值 0.694；判断 `low_independence_template_repetition`。
- `category-template::价格与预算::chunk-3`：7 chunks；文本相似均值 0.807；向量 cosine 均值 0.772；判断 `low_independence_template_repetition`。
- `category-template::参数判断::chunk-0`：8 chunks；文本相似均值 0.905；向量 cosine 均值 0.784；判断 `low_independence_template_repetition`。
- `category-template::参数判断::chunk-1`：8 chunks；文本相似均值 0.858；向量 cosine 均值 0.807；判断 `low_independence_template_repetition`。
- `category-template::参数判断::chunk-2`：8 chunks；文本相似均值 0.836；向量 cosine 均值 0.741；判断 `low_independence_template_repetition`。
- `category-template::概览::chunk-0`：8 chunks；文本相似均值 0.903；向量 cosine 均值 0.739；判断 `low_independence_template_repetition`。
- `category-template::概览::chunk-1`：8 chunks；文本相似均值 0.855；向量 cosine 均值 0.793；判断 `low_independence_template_repetition`。
- `category-template::概览::chunk-2`：8 chunks；文本相似均值 0.827；向量 cosine 均值 0.725；判断 `low_independence_template_repetition`。
- `category-template::避坑与合规::chunk-0`：8 chunks；文本相似均值 0.904；向量 cosine 均值 0.779；判断 `low_independence_template_repetition`。
- `category-template::避坑与合规::chunk-1`：8 chunks；文本相似均值 0.869；向量 cosine 均值 0.834；判断 `low_independence_template_repetition`。
- `category-template::避坑与合规::chunk-2`：8 chunks；文本相似均值 0.837；向量 cosine 均值 0.686；判断 `low_independence_template_repetition`。
- `category-template::避坑与合规::chunk-3`：7 chunks；文本相似均值 0.807；向量 cosine 均值 0.768；判断 `low_independence_template_repetition`。
- `policy-template::chunk-0`：8 chunks；文本相似均值 0.825；向量 cosine 均值 0.849；判断 `low_independence_template_repetition`。
- `policy-template::chunk-1`：8 chunks；文本相似均值 0.773；向量 cosine 均值 0.835；判断 `low_independence_template_repetition`。
- `policy-template::chunk-2`：8 chunks；文本相似均值 0.715；向量 cosine 均值 0.762；判断 `low_independence_template_repetition`。
- `policy-template::chunk-3`：8 chunks；文本相似均值 0.692；向量 cosine 均值 0.790；判断 `requires_human_review`。

## v4-006 Flash Top-20

20/20 均为 `eval-travel-gear-*` 或 `eval-home-living-*` synthetic fixtures，且均不包含 gold evidence。
它们是同领域模板化 decoy，在评测中可作为困难负例；但由于进入运行时 collection，也证明 production/evaluation 未隔离。

## 建议

应该启动独立 Corpus Hygiene Experiment，但先建立明确的 production allowlist/目录/collection。
清理后的提升必须归因于 corpus isolation，而不是 embedding。当前不应继续 D0-instruct：否则会用 instruct 去拟合本应由语料隔离解决的 fixture competition。
也没有证据启动 Chunk Experiment E。
