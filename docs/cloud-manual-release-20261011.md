# 2026-10-11 用户授权的人工发布

用户要求停止付费评测并直接上线。本次明确记为 `operator_publish`，
`evaluation_status=INCOMPLETE`，不是完整成对评测 PASS。正常发布门禁保持原样。
服务器仍需构建、预检查、备份、启动和浏览器验收。本机没有 Docker，脚本测试使用模拟 Docker。

## 上传与执行

上传 `globex-repair-20261011.tar.gz` 至 `/home/admin/`，在 Workbench 终端逐行执行：

```bash
mkdir -p /home/admin/globex-releases/20261011-manual-repair
tar -xzf /home/admin/globex-repair-20261011.tar.gz -C /home/admin/globex-releases/20261011-manual-repair
GLOBEX_MANUAL_RELEASE=1 bash /home/admin/globex-releases/20261011-manual-repair/scripts/update_cloud.sh
```

- `mkdir -p` 创建独立发布目录。
- `tar -xzf` 解压上传的文件；`-C` 指定目标目录。
- `GLOBEX_MANUAL_RELEASE=1` 明确选择人工发布；`bash` 执行更新脚本。

脚本复用当前恢复后的实际数据卷和 .env，先构建并只读核对升级来源、代码指纹、
候选正文和工具契约，然后停服备份三个数据卷，记录人工发布并启动。
不会使用评测固定版本配置，也不会删除注册表或更改旧会话绑定。
首次索引最多等待 20 分钟；终端定期显示最近启动日志。
成功时打印 `[5/5] Server responds`、Release、Backup 和认证状态。

默认保留当前商品库。ABO 商品集包含在包内，暂未切换启用。
通过原 SSH 隧道打开页面，检查登录、新聊天、商品检索和已有订单。
旧聊天如提示版本更新，请新建聊天；历史记录和订单保留。

## 出错

保留终端输出。预检查失败时旧服务仍运行；启动后失败时不要只切旧镜像读新数据。
如需恢复，使用脚本打印的本次真实备份路径：

```bash
bash /home/admin/globex-releases/20261011-manual-repair/scripts/rollback_cloud.sh /home/admin/globex-backups/本次备份时间
```
