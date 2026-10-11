# 2026-10-11 内测服务器更新

范围：融合 v3.5–v3.7、DeepSeek 协议修复和共享邀请登录。继续绑定
`127.0.0.1:5173`，域名及公网 HTTPS 单独配置。此次不是公网发布。

## 执行

把 `globex-update-20261011.tar.gz` 上传至 `/home/admin/`，然后在服务器终端执行：

```bash
mkdir -p /home/admin/globex-releases/20261011
tar -xzf /home/admin/globex-update-20261011.tar.gz -C /home/admin/globex-releases/20261011
bash /home/admin/globex-releases/20261011/scripts/update_cloud.sh
```

- `mkdir -p`：创建目录；已存在也不会报错。
- `tar -xzf`：解开 gzip 压缩的 tar 包；`-C` 指定解压位置。
- `bash`：运行脚本。脚本需要 sudo，可能提示输入服务器账号密码。

脚本从当前容器发现全部活动 Compose 配置和三份实际命名卷（包括回滚恢复卷），复制活动部署的 `.env`，构建带提交号的
新镜像；构建后先执行只读 Prompt 预检查，通过后才短暂停服，对 SQLite/Redis/Qdrant 所在完整数据卷做备份并
验证归档可读，再启动新版。模型加密密钥也随完整 app-data 卷备份。
备份位于 `/home/admin/globex-backups/UTC时间/`，含敏感配置，仅供管理员保存。
不会重新导入本机运行数据库，也不会删除原有卷。

前端在本机构建为 dist，服务器只需打包 Nginx 镜像，不必再次运行 npm ci。
后端仍需服务器构建，依赖下载是否可用须通过现场输出判断。

## 启动后验收

`/health` 和 `/commerce/auth` 可访问仅代表基础就绪。继续通过已有 SSH 隧道
打开页面，检查登录、聊天、商品检索、历史会话搜索、订单与收藏、模型配置和
自动化任务。保留已有确认订单并核验原订单仍可查询；使用两个不同身份核验隔离。
自动化实际执行可能调用模型并消费额度，使用合成测试数据。

当前活动发布目录写入 `/home/admin/globex-active-release.txt`。
后续 Compose 操作必须同时使用该目录的主配置及 `docker/release.override.yaml`，
不要再用旧目录配置执行 up，否则可能切回旧镜像。

```bash
release=$(cat /home/admin/globex-active-release.txt)
sudo docker compose -p globex -f "$release/docker/docker-compose.cloud.yaml" -f "$release/docker/release.override.yaml" ps
sudo docker compose -p globex -f "$release/docker/docker-compose.cloud.yaml" -f "$release/docker/release.override.yaml" logs --tail=60 app worker frontend
```

`cat` 读取文件；`$(...)` 把命令输出保存到变量；`-p` 指定项目名；
`-f` 指定配置文件；`ps` 查看状态；`logs --tail=60` 查看各服务最后 60 行日志。
反馈日志前遮住密钥、邀请链接和个人资料。

## 回滚

出现错误先保留输出。新版本启动前备份失败会自动尝试重启原服务；
启动后失败不会自动用旧镜像读取可能已经迁移的数据。

确需恢复时，将下面的 `备份时间` 替换为脚本打印的真实目录名：

```bash
bash /home/admin/globex-releases/20261011/scripts/rollback_cloud.sh /home/admin/globex-backups/备份时间
```

脚本核验备份校验和，将三份备份恢复至新的命名卷，再切换旧镜像。
原始卷仍保留，但更新后新增的数据不会出现在恢复的旧版本中。
回滚后的配置路径会打印到终端，后续操作必须使用备份目录里的主配置和该覆盖配置。

## Prompt 与工具代码一起升级

旧注册表中的 Prompt 绑定原工具代码。更换工具时不能删除注册表或把旧会话偷偷切到新版本。
更新包需要包含 `prompt-upgrade/`：

- `upgrade.json`：原部署 Prompt ID、新工具下的基线及候选 ID。
- `candidate.yml`：候选正文。
- `baseline.manifest.json`、`candidate.manifest.json`：同一冻结代码和 release 全集真实执行的成对报告。

脚本在停服前检查报告必须全部通过，并核对镜像代码指纹、工具契约及当前部署来源。
没有报告或报告失败，升级在停服前被阻止。通过后先停服备份，再追加新发布记录并启动。
原版本和会话绑定保留；旧契约会话需新建聊天，历史数据不被删除。

`apply_prompt_upgrade --check` 只读验证；去掉 `--check` 才会追加发布记录。
评测用的 `PROMPT_PIN_VERSION` 不得留在生产配置中。

## 验证范围

本机升级注册表、只读检查、拒绝篡改报告、重复执行和会话绑定测试通过。
使用模拟 Docker 的完整脚本演练覆盖回滚卷发现、三个卷的备份、继承覆盖配置、
升级检查失败时不停止旧服务。本机没有 Docker，模拟不能代替服务器镜像运行验收。
真实模型 release 成对报告单独记录；单元测试使用的合成证据不作为发布许可。
