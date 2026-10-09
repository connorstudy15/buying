# Phase 2.5：Continuation targeted smoke 结果

采集：2026-10-09；收尾核验：2026-10-10。结论：**Phase 3 NO_GO，继续 shadow-only**。

## 1. 实际执行范围

重启后先做两个 instrumentation 探针，再尝试预先声明的 16 条 targeted 请求。
没有跑完整 67×2，没有修改检索参数、mandatory flow、RRF、reranker 或正式候选链路。
DEEPSEEK_V41_TOKENIZER_PRIMARY 保持 0，80K hard cap 仅观察。

原计划按 case 隔离为校准 8 条 / 验证 8 条，探针不进入任何集合。
DeepSeek 在第 12 条中途返回 `402 Insufficient Balance`；此后请求也未正常完成。
最终有效 **11 条：校准 6 条 / 验证 5 条**。未补跑、未充值、未切换模型。
长上下文与证据不足专项没有成功完成，不能宣称这些场景已验证。

原始 runner 将 HTTP 200 误记为 success：同步接口 DTO 只返回 final_text，丢掉了内部 error 字段。
因此原始 runs.json 的 “16 success” 不代表业务执行成功。
原始文件保留不覆盖；audited-runs.json 另存 main.final 完成态审计。
main.final 仅证明可观测生命周期完成，不代表答案或检索质量正确。

排除的 case：

| Case | 原定集合 | 排除依据 |
|---|---|---|
| p25v3-search-05 | calibration | 上游余额不足，中途失败，无 main.final |
| p25v3-context-01 | calibration | 失败，无有效 main 生命周期结束 |
| p25v3-search-06 | validation | 失败，无有效 main 生命周期结束 |
| continuation-context-02 | validation | 失败，无有效 main 生命周期结束 |
| continuation-insufficient-01 | validation | 失败，无有效 main 生命周期结束 |

## 2. 本轮修复

- Langfuse v2 下载接口将长 JSON metadata 截为 200 字符预览：节点存在，但旧解析器无法还原 runtime snapshot。
- 增加受脱敏白名单约束的标量传输、字段数量完整性校验和还原；旧 JSON 仍保留兼容。
- runner 每条请求完成后保存进度；识别 `[error]` final_text，余额不足时终止后续采集。
- 固定 split 检查 case 重叠、重复、缺失；排除失败/未完成主生命周期，保留排除清单。
- 输出逐 case 指标，避免长请求事件数淹没简单请求的退化。

修复前探针：runtime 事件无法还原。修复后探针：成功还原 4 个事件。
11 条有效请求共还原 **419 个 runtime events**，没有整条 trace 缺失 runtime events。
离线训练仍只接收 flow sequence 连续的数据；未结束 flow 的剩余轮数目标保持 censored。

## 3. 独立验证结果

校准数据只来自 6 个独立 case；验证数据只来自另外 5 个 case。
使用当时保存的 causal snapshot 作为特征，后续事件只用于构造监督标签。
没有使用请求最终 route/operation count 回填早期特征。
next-operation 指同一 flow 的下一个可观测完成事件，不是跨 Agent 的 HTTP 调用顺序。
final → END 的简单协议样本不纳入准确率。

| 指标 | 空 profile / bootstrap | 冻结校准 profile |
|---|---:|---:|
| Next Top-1，236 个验证事件 | 42.37% | 58.90% |
| Next Top-3，236 个验证事件 | 52.12% | 85.17% |
| Main 剩余规划轮数 MAE，229 个可评估事件 | 无可用估计 | 0.752 轮 |
| Search 剩余规划轮数 MAE，229 个可评估事件 | 无可用估计 | 0.352 轮 |

剩余轮数 baseline 原本为 null，不能说 MAE 从某个旧值下降。
以上为 event-weighted 指标；236 个事件不是 236 个独立请求。
两个复杂 Search case 贡献 199/236（84.3%）事件。

| 验证 case | N | Top-1 baseline → calibrated | Top-3 baseline → calibrated |
|---|---:|---:|---:|
| p25v3-direct-02 | 4 | 25.0% → 0.0% | 25.0% → 50.0% |
| p25v3-knowledge-02 | 25 | 40.0% → 40.0% | 44.0% → 60.0% |
| p25v3-product-02 | 8 | 50.0% → 75.0% | 62.5% → 100.0% |
| p25v3-search-02 | 101 | 42.6% → 62.4% | 53.5% → 88.1% |
| p25v3-search-04 | 98 | 42.9% → 61.2% | 53.1% → 88.8% |

按 case 等权平均：Top-1 约 40.09% → 47.72%；Top-3 约 47.61% → 77.38%。
简单 DIRECT Top-1 有退化，且 Main 剩余轮数 MAE 在 direct/product 两例分别约 2.03/2.40 轮。
因此不能仅凭总体准确率宣称 Predictor 稳定，更不能进入 action-driving。

验证预测置信度：LOW 229 个事件，BOOTSTRAP 7 个，MEDIUM/HIGH 均为 0。
P50/P80/P95 轮数分位数均无足够独立 group 支持，coverage N=0，值为 null。
线上仍使用空 profile；本轮离线 artifact **未自动加载到线上**。

## 4. Accounting、资源长尾与 causal revision

16 条尝试的导出记录：accounting error、reservation leak、duplicate accounting、stale execution 均为 0。
这只说明账本内部对账一致，不能把失败调用的估计值当成已验证的 Provider 计费真值。

11 条有效请求的记录总聊天 token：1,388,550；其中 5 条 >80K，4 条 >150K，最大 305,397。
成本字段没有可用金额数据，不能由此给出人民币花费。
80K 不能开启真实硬拒绝，也不能把复杂混合请求统一学成固定 200K profile。

同一次执行的 revision 0 → first-informed checkpoint 诊断：

- 请求 token MAPE：68.91% → 47.72%。
- operation-count MAE：25.00 → 19.91。
- 低估率：63.64% → 63.64%，没有下降。
- 低估 P95 shortfall：263,700 → 227,103 tokens，仍然很大。

这不是两版软件的受控 A/B，也不是把 continuation profile 接入预算后的收益。
两个 checkpoint 已知信息不同；不能把这些数字包装成此次离线校准降低了真实 token 消耗。

419 个 runtime events：UNKNOWN 155、LOW_PROGRESS 262、MEDIUM_PROGRESS 2。
evidence sufficiency 全部 UNKNOWN；没有经可靠标注确认的 ZERO_PROGRESS 样本。
所以不能证明“零进展后仍继续”的检测已经有效，也不能因为检索有返回就认为 evidence sufficient。

## 5. Gate 与下一步

- 当前相关本地回归：**136 passed**，不是整个项目全量测试。
- Retrieval Quality Regression：本轮 NOT_RUN；targeted 数据没有 relevance gold，不可替代该 Gate。
- DeepSeek Golden Tokenizer Parity：本轮未完成；PRIMARY 继续 0。
- 置信度不足，简单请求有退化，资源长尾低估仍大：**Phase 3 NO_GO**。
- 不取消 mandatory/Main Final，不改变 need、候选深度、模型或 DECOMPOSE。

下一步需要账户恢复可用后，先补齐失败的 5 个原定 case（新 session，仍按原 split），
再检查简单请求的 profile 回退污染；不要把验证 case 追加进训练后仍声称它是独立验证。
本轮不自动重试付费调用。

## 6. 结果文件

- 原始采集记录：`eval/resource-governance/continuation-v1-targeted-runs.json`
- 完成态审计：`eval/resource-governance/continuation-v1-audited-runs.json`
- 全部 16 条导出：`eval/resource-governance/continuation-v1-targeted-report.json`（含失败请求，整体 token/latency 指标不可作为有效样本统计）
- 隔离集合：`eval/resource-governance/continuation-v1-isolated/calibration.json`、`validation.json`、`valid.json`
- 独立验证：`eval/resource-governance/continuation-v1-validation-report.json`
- 冻结离线 profile：`eval/resource-governance/continuation-v1-profiles.json`
- 有效 11 条 causal replay：`eval/resource-governance/continuation-v1-causal-report.json`、`.md`
