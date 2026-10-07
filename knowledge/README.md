# Production knowledge

应用运行时只读取 `knowledge/production/`，并写入 `globex_category_kb`。

- manifest 必须声明 `corpus_role=production`。
- `source_type` 仅允许 `production_knowledge`、`official_guide`、`curated_knowledge`。
- 缺少 manifest、来源类型或角色时，production admission 会拒绝入库。
- 评测 fixture 不得放在这里；它们位于 `eval/knowledge/corpus/`。

当前切块策略保持 `512 tokens / overlap 50`，本轮没有进行 chunk 调参。
