# Open Icecat 商品检索评测

本目录用于把 Open Icecat 商品数据接入 Globex 现有的 `eval/v1` 评测体系。

## 1. API 预检

1. 在项目根目录 `.env` 中设置 `ICECAT_USERNAME` 和 `ICECAT_API_TOKEN`。
2. 运行：

   ```powershell
   uv run python scripts/eval/icecat_preflight.py
   ```

预检只请求一个商品，不保存响应，也不会打印凭据。通过后才进入索引下载、类目
抽样和字段标准化阶段。

## 2. 构建扩展商品库与 benchmark

脚本复用现有 `CatalogSearchUseCase`、三档依赖注入 runner 和 `metrics.py`，不会另造
一套评测框架：

```powershell
.\.venv-eval\Scripts\python.exe scripts/eval/build_icecat_product_eval.py
```

默认抽取三个 Open Icecat vertical、每类 300 个真实商品；输出合并后的 1400 商品
catalog，以及 300 条 benchmark（原 67 条为 `regression`，新增 233 条为
`icecat_candidate`）。新增标注是按结构化商品事实自动生成的候选标注，正式门禁前必须
人工复核，字段 `annotation_status=auto_derived_needs_review` 会保留这一状态。

运行现有真实检索链路：

```powershell
.\.venv-eval\Scripts\python.exe scripts/eval/run_product_recall.py `
  --dataset eval/icecat/private/product_recall-300.jsonl `
  --catalog data/icecat-catalog.jsonl `
  --strategy keyword_2gram
```

向量、精排、hybrid 三档继续使用原 runner 的 dependency injection 参数，不在数据
构建脚本中模拟。默认 K 仍为 8，与当前实际向量 recall depth 对齐。

## 数据边界

- `raw/`、`cache/`、`private/` 已加入 `.gitignore`。
- Icecat 原始数据仅作内部检索评测，不用于模型微调或训练。
- 公开仓库只保存自行编写的评测逻辑；原始商品内容及凭据不提交。
- 价格、库存、配送国家和评分是确定性合成的评测运营层；每条记录都在
  `evaluation_provenance` 中标明，不能当成 Icecat 或真实店铺报价。
