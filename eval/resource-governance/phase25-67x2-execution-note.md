# Phase 2.5 67×2 执行记录

- Manifest: `phase25-67x2-runs.json`
- Requested observations: 134（67 cases × 2 repetitions）
- Runner records: 132 success, 2 `ReadTimeout`
- Timeout cases: `v4-028`、`v4-038`（均为 repetition 1，300 秒）
- Provider warning: `.runlogs/phase25-final.stderr.log` 中出现 `AccessDenied.Unpurchased`；本次运行的旧 runner 只依据 HTTP 状态码，不能把这些业务层失败从 200 响应中区分出来，因此本 manifest 不能作为最终质量/延迟结论。

已修正 `scripts/resource_governance/run_phase25_benchmark.py`：后续运行会识别响应 JSON 中的 `error`、`ok=false`、`status=error/failed`，并将其标为 error。

本次未生成最终 `phase25-report.json`：Langfuse 拉取受到当前环境代理/网络限制；检索质量 67×2 也未完成，因本地 Qdrant 锁与评测进程冲突而停止。不得把本记录中的 HTTP 200 数量当作通过结论。
