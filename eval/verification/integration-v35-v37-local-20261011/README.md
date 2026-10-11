# 上游功能融合测试证据

- baseline: 37df884 / cloud-beta-20261011
- upstream: ddd7e5be1af4bb474f3af325f3d5113051c1c013
- 前端：245 passed；生产构建成功。
- backend-full-initial.log：2072 passed, 12 failed, 44 skipped。
- backend-fixes-final.log：修复后相关套件 120 passed，含真实应用装配与 HTTP 身份隔离。
- startup-http.log：单独启动身份隔离测试 1 passed（已包含在上述 120 中，不重复加总）。
- 真实模型 r4：847 contracts passed；10/12 场景执行通过，两次商品重新核验 BadRequestError；门禁未通过。
- 未部署云端。失败证据保留，不声称生产验收或成本收益通过。
