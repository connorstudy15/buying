# Phase 2.5：Calibration & Validation

## 当前状态

- Resource Governor 继续 `shadow-only`。
- 没有启用 request rejection、mandatory rejection、强制检索降级或模型降级。
- 80K 仍是 bootstrap absolute hard cap，仅记录是否会越界。
- `LOW` / `BOOTSTRAP` Profile 不具备 action-driving 资格。
- 原有知识检索评测仍是质量真值；资源评测不复制、不替换 Retrieval Eval。

## 单次调用 Token 估算

同一次 Agent 模型调用记录：

- `old_estimated_prompt_tokens`：旧 bytes/4 estimator；
- `deepseek_estimated_prompt_tokens`：DeepSeek V4.1 estimator；
- `deepseek_safe_estimated_prompt_tokens`；
- `actual_input_tokens` / `actual_output_tokens`：Provider usage，结算唯一真值；
- 两个 estimator 的 `actual / estimate ratio`；
- `local_estimated_output_reserve`。

估算点已经下沉到 OpenAI SDK 的 HTTP request hook：它在
`POST .../chat/completions` 真正发送前读取最终 JSON body，完成计数后立即丢弃正文。
因此 estimator 与线上请求共享 formatter 之后的 `messages`、完整 tool schema、
`tool_choice`、assistant tool calls、tool results、`enable_thinking/thinking` 和
`reasoning_effort`。AgentScope Msg 阶段的结果仅标记为 `agent_message_fallback`，不能
成为 high-confidence 或 PRIMARY 依据。

DeepSeek 高置信度路径使用官方 `deepseek_recipe.ChatCompletionRequest`、
`ConversionOptions`、`DeepseekV41Encoding` 和匹配的本地 `tokenizer.json`。
运行时禁止下载 tokenizer。

项目现已内置 DeepSeek 官方仓库提供的 V4.1 `tokenizer.json`，并在加载前校验官方
SHA-256 `81f64d1248a68ce3663e07ab3ee48b851e5df0e32d27cb98e4c9a268151e8d99`。
`.gitattributes` 禁止 Git 对该文件进行 Windows 换行转换。

官方 `deepseek-recipe==0.1.1` 当前只发布 Linux/macOS wheel，没有 Windows wheel。
因此 Windows 开发机仍会明确使用 `deepseek_v41_recipe_unavailable_fallback`；Linux
部署通过 `pyproject.toml` 的平台依赖安装官方包后，才能进入 high-confidence 路径。
完成 API actual 校准前不得把新 estimator 切为 PRIMARY。

Windows 备选调查结论：DeepSeek 官方 Hugging Face 模型仓库的最新版本存在独立
`encoding/encoding_dsv4.py`，可使用普通 Python 生成 prompt；但项目固定的 tokenizer
来源 revision 与该 encoding 版本并非同一个经过验证的发布组合，而且官方 recipe 目前
仍有 special-token-like 用户正文与历史 reasoning 的公开 parity 边界案例。因此本轮只把
它登记为候选，不复制或改写其 prompt encoding，也不标记 high confidence。只有固定官方
commit、vendor 官方文件、验证输出 token IDs 与 recipe 一致并通过本项目 14 类 Golden
parity 后才可接入 Windows 正式估算。

Calibration profile 只按 provider/model/protocol/prompt encoder/prompt version/thinking/
reasoning/tooling 切分，不加入 DIRECT/DECOMPOSE 或 evidence route。样本数 `<30` 为
BOOTSTRAP，`30~99` 为 MEDIUM，`>=100` 才是 HIGH 候选；安全系数取本 profile、父 profile
与配置下限的最大值，5 条样本不会启用 P95。

配置：

```dotenv
DEEPSEEK_V41_TOKENIZER_PATH=assets/tokenizers/deepseek-v41/tokenizer.json
DEEPSEEK_V41_TOKENIZER_PRIMARY=0
```

不读取 prompt/API key 的能力检查：

```powershell
python scripts/resource_governance/check_deepseek_tokenizer.py
```

Linux 发布流水线可加 `--require-ready`，缺少官方包、资产或哈希不一致时返回非零：

```bash
python scripts/resource_governance/check_deepseek_tokenizer.py --require-ready
```

Gate 通过以前 `PRIMARY` 必须保持 `0`。如果官方包或 tokenizer 不可用，系统明确降级为
`model_count_tokens_generic` 或 `formatted_utf8_upper_bound`，不会标记为 high confidence。

## Accounting Reconciliation

请求结束时自动检查：

- FutureWorkPlan 与 ReservationManager 的一对一关系；
- active reservation 是否归零；
- `(logical_call_id, attempt)` 是否重复；
- missing usage 与 timeout estimated settlement 数量。

离线报告进一步把 Resource operation actual 与 Langfuse Generation usage 对账。
存在无法由 missing usage、timeout 或 provider anomaly 解释的差异时，先修 Accounting，
不得调 WorkloadPredictor。

## 67-query 资源回归

冻结集合为：

- `knowledge_eval_core_61.jsonl`
- `knowledge_eval_partial_coverage_2.jsonl`
- `knowledge_eval_knowledge_gap_4.jsonl`

合计 67 条。完整 Agent 运行命令：

```powershell
python scripts/resource_governance/run_phase25_benchmark.py `
  --base-url http://127.0.0.1:8000 `
  --repetitions 2 `
  --output eval/resource-governance/phase25-agent-runs.json
```

建议先 `--limit 3` 冒烟，然后再执行 67×2。该命令产生真实 API 费用。
使用 `--base-url` 可以复用已启动服务，避免第二个进程争抢本地嵌入式 Qdrant 文件锁；
服务必须先重启以加载 Phase 2.5 埋点。

原 Retrieval Quality Eval 必须另外执行并保留原门禁。资源报告没有权力自行宣布质量通过。

Golden parity（14 类固定 payload）先导出真实 Main Agent tool schema，再调用百炼：

```powershell
python scripts/resource_governance/dump_main_agent_tool_schema.py `
  --capture <一次本地主 Agent final-request capture.json> `
  --output eval/resource-governance/main_agent_tool_schema.json
python scripts/resource_governance/run_tokenizer_golden_parity.py `
  --main-tool-schema eval/resource-governance/main_agent_tool_schema.json `
  --output eval/resource-governance/deepseek-v41-golden-parity.json
```

## 报告

从 Langfuse 读取数值字段生成报告：

```powershell
python scripts/resource_governance/phase25_report.py `
  --fetch-langfuse `
  --lookback-days 7 `
  --run-manifest eval/resource-governance/phase25-agent-runs.json `
  --golden-parity-report eval/resource-governance/deepseek-v41-golden-parity.json `
  --retrieval-quality-status NOT_RUN `
  --output eval/resource-governance/phase25-report.json
```

`--run-manifest` 是正式回归报告的必需输入：它把 Langfuse trace id 映射回 case id，
并排除同一时间窗口内无关的开发请求。只有现有 Retrieval Quality Eval 独立通过后，
才把 `--retrieval-quality-status` 改为 `PASS`。

报告包含：Accounting、旧 estimator 与 DeepSeek estimator 对比、请求/operation 误差、
route/query type/subquery count 分桶、underprediction 分布、Profile confidence、planned budget
和 80K hard cap 超限率，以及 Phase 3 Go/No-Go。

## Phase 3 Gate

当前 Gate 至少要求：

- 67 个唯一 case，每条至少 2 次，共不少于 134 条匹配 Trace；
- 14 类 Golden tokenizer parity 明确通过；
- Retrieval Quality Regression 明确通过；
- accounting error、reservation leak、duplicate accounting、stale execution 均为 0；
- overall underprediction rate < 10%；
- overall 与 Main Final 的 P95 underprediction shortfall ratio <= 10%；
- planned budget exceed rate <= 10%；
- mandatory erroneous rejection 和 Main Final protection failure 均为 0。

即便 Gate 通过，Phase 3 首批 action-driving 也只能影响 optional/speculative operation。
