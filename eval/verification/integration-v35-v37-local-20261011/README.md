# 上游功能融合测试证据

- baseline: 37df884 / cloud-beta-20261011
- upstream: ddd7e5be1af4bb474f3af325f3d5113051c1c013
- 前端：245 passed；生产构建成功。
- backend-full-initial.log：2072 passed, 12 failed, 44 skipped。
- backend-fixes-final.log：修复后相关套件 120 passed，含真实应用装配与 HTTP 身份隔离。
- startup-http.log：单独启动身份隔离测试 1 passed（已包含在上述 120 中，不重复加总）。
- 历史 r4/r5：商品核验 BadRequestError，失败证据保留。
- 最终 r6：857 contracts passed；12/12 次真实模型场景执行通过，source_stable=true，harness verify passed=true。
- deepseek-forced-tools-tests.log：66 passed，覆盖强制工具/后续工具结果/下一用户轮次及其他网关隔离。
- 成本收益门禁仍为 BLOCKED，未证明成本收益。
- 未部署云端。失败证据保留，不声称生产验收或成本收益通过。
