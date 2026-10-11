# Ezbuying 账号注册与登录

## 范围

- 用户名（3–32 位英文、数字、下划线、点、短横线，大小写不敏感）与密码注册；昵称最多 32 个字符。
- 新注册密码为 6–12 个字符（旧账号的长密码仍可登录），使用随机 16 字节盐和 PBKDF2-HMAC-SHA256（600,000 次），不存明文。
  参数参考 [OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)。
- 注册完成自动登录；账号 Cookie 为 HttpOnly、SameSite=Lax，公网 HTTPS 使用 Secure 与 __Host- 前缀。
- 登录有效期 7 天；退出立即撤销当前会话，其他设备保持登录。到期需重新登录。
- 登录频率持久限制：每账号每 15 分钟最多 10 次，全站最多 120 次；注册全站每 15 分钟最多 20 次。重启不清零。
- 同一账号使用稳定的 account-* buyer_id，接入原有会话、收藏、意向单、偏好与自动化任务归属检查。
- 左下角昵称与头像首字来自服务端验证的身份；邀请访客显示“体验访客”。
- 保留个人内测凭证及共享邀请，打开邀请链接不会把已登录账号降为访客。
- 本版不自动迁移访客记录，不提供短信、第三方登录、自助密码找回或昵称编辑。

## 接口和存储

- POST /commerce/auth/register：username、password、display_name。
- POST /commerce/auth/login：username、password。
- GET /commerce/auth：登录状态、buyer_id、credential、display_name、username（账号）。
- POST /commerce/auth/logout：撤销当前登录并清 Cookie。

账号数据库为 DATA_DIR/accounts.db，与现有数据卷一起持久化和备份，不改变原业务表结构。
浏览器不保存密码或可供 JavaScript 读取的账号令牌。前端缓存按买家身份检查，切换身份不会复用他人会话缓存。
注册、登录及 Cookie 写请求校验 Origin；公网要求 HTTPS，HTTP 仅允许回环开发。
反向代理需保留公网 Host；本地代理改写 Host 时，通过 CORS_ORIGINS 显式允许开发源。
账号不是管理员身份，不能因为注册获得模型密钥管理或运维读取权限。

## 云端更新

上传 ezbuying-accounts-20261011.tar.gz 到 /home/admin/，在 Workbench 执行：

```bash
mkdir -p /home/admin/globex-releases/20261011-accounts
tar -xzf /home/admin/ezbuying-accounts-20261011.tar.gz -C /home/admin/globex-releases/20261011-accounts
GLOBEX_CATALOG=abo bash /home/admin/globex-releases/20261011-accounts/scripts/update_cloud.sh
```

用户已授权为 720 件 ABO 演示商品生成 embedding。上述命令同时启用这批商品；原目录及向量集合保留。
先启动 app 建库，前端/后端就绪且新集合点数为 720 后再启动 worker，减少同时重复推理。
首次启动会消费 embedding 额度；本次不运行付费聊天评测。没有实机执行前不能保证建库成功或实际费用。
若只发布账号功能、保留原目录，去掉 GLOBEX_CATALOG=abo。

脚本发现当前实际数据卷和 Compose 配置，构建后检查已有 Prompt 兼容，停服备份全部三个卷再启动。
本次未修改工具契约或 Prompt，不需要重发 Prompt，也不需要人工绕过评测门禁。
保留脚本输出中的 Backup 路径，恢复时使用 scripts/rollback_cloud.sh 和该实际路径。
本机未安装 Docker，脚本流程使用模拟 Docker 测试；实机运行与浏览器验收仍需完成。

## 验收

1. 用普通窗口注册 alice/昵称“小爱”，左下角和顶部显示“小爱”。
2. 新建聊天及收藏；退出，再登录同一账号，确认数据恢复。
3. 无痕窗口注册 bob/昵称“小波”，确认看不到 alice 的聊天、收藏和订单。
4. 换浏览器登录 alice，确认能恢复 alice 的记录。
5. 邀请链接仍可直接进入，显示“体验访客”，不与其他浏览器共享记录。
6. 检查 app/worker 日志和新商品检索；测试聊天会使用模型额度。
