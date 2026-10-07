# Evaluation knowledge corpus

`corpus/` 保存离线 Retriever stress benchmark 使用的合成语料。45 篇文档会切成
151 个 chunk，并存入独立的 `globex_category_kb_eval` collection。

普通评测 runner 只验证已冻结 collection，不自动重切块或重算向量。需要重建时必须使用
显式迁移/重建脚本，避免把兼容接口向量覆盖到冻结的 role-aware collection。

这些文档包含 hard negative 与重复模板，只用于评测，不得被应用运行时加载。
