# 共享 HR 邀请链接

所有 HR 使用同一个链接。入口只允许进入演示，服务器为每个浏览器签发不同的 `guest-*` 身份，聊天、收藏、会话和意向单按既有 owner 规则隔离。持有链接的人都能进入，因此链接适合受邀演示；它不会区分来访者是不是 HR。

## 使用前提

- 部署本次后端和前端，设置 `IDENTITY_MODE=hmac`、足够长的 `IDENTITY_HMAC_SECRET`、`SESSION_OWNER_BINDING=1`。原来的个人 Bearer 凭证仍可使用。
- 访客通过 HTTPS 访问同一个前端/API 入口（现有 Nginx 将 `/commerce/` 转给 API）。`--origin` 填浏览器实际地址的源：协议、域名、可选端口，不含 `/demo` 路径。
- 当前云端 `127.0.0.1:5173` 是本机入口，不能直接当作 HR 的公网链接。本次代码不自动配置域名、证书或开放安全组。
- 本机开发允许 `http://localhost:5173` 或回环 IP；其他 HTTP 地址不能签发邀请。正式 HTTPS Cookie 会自动设置 Secure，WebSocket 使用 WSS。

## 创建一个供所有 HR 共用的链接

在云服务器的终端执行，先将 `https://YOUR_DOMAIN` 换成实际 HTTPS 地址：

```bash
cd /home/admin/globex
sudo docker compose -p globex -f docker/docker-compose.cloud.yaml exec -T app python -m scripts.manage_invites create --origin https://YOUR_DOMAIN --days 7 --output /app/data/shared-hr-invite.txt
```

- `cd`：切换到项目目录。
- `sudo`：以管理员权限运行 Docker。
- `docker compose`：管理项目中的容器；`-p globex` 指定项目名，`-f` 指定配置文件。
- `exec -T app`：在正在运行的 app 容器中执行命令，不进入交互终端。
- `python -m scripts.manage_invites create`：运行本机邀请管理程序，创建邀请。
- `--origin`：访客打开网站的真实源地址，不能填容器内部地址。
- `--days 7`：邀请有效 7 天，可设为 1–90 天。浏览器登录默认最长 24 小时，可用 `--session-hours` 调整到 1–168 小时，但不能超过邀请到期时间。
- `--output`：链接保存到只有文件拥有者能读写的新文件，拒绝覆盖已有文件。控制台只返回邀请 ID 和文件路径。

查看文件、复制整条链接：

```bash
sudo docker compose -p globex -f docker/docker-compose.cloud.yaml exec -T app cat /app/data/shared-hr-invite.txt
```

`cat` 表示显示文件内容。文件里的 `https://…/demo#invite=…` 就是给所有 HR 的同一个链接。不要将该文件提交到 GitHub 或公开截图。

## 查看与撤销

```bash
sudo docker compose -p globex -f docker/docker-compose.cloud.yaml exec -T app python -m scripts.manage_invites list
```

`list` 列出邀请 ID、入口、到期时间及撤销状态，不显示原始邀请码。

```bash
sudo docker compose -p globex -f docker/docker-compose.cloud.yaml exec -T app python -m scripts.manage_invites revoke --invite-id INVITE_ID
```

`revoke` 撤销指定邀请；把 `INVITE_ID` 替换为列表中的 ID。共享链接和关联浏览器登录的后续请求都会失效。WebSocket 最长约 30 秒重新核验，前端最长约 60 秒重新核验。已经开始执行的一轮请求不会因此被强制取消；彻底停止演示需停止服务。

## 登录行为和存储

- 邀请码放在 URL fragment 中，不传给静态服务器；页面读取后立即从地址栏移除，再用 POST 兑换登录，不把邀请或登录凭证写入 JS 存储。
- 服务端返回 HttpOnly、SameSite=Lax 的随机 Cookie。Cookie 有效时刷新、再次打开同一链接均保留浏览器身份；无痕窗口或另一台设备创建独立身份。
- Cookie 请求验证 Origin，写入请求及 WebSocket 必须来自邀请指定源地址。显式 Bearer 优先，错误 Bearer 不回退到 Cookie。
- 点击退出会删除服务端登录记录及 Cookie；随后重新使用共享链接会获得新身份。原有记录不会因此删除，但新身份不能读取旧身份记录。
- 数据库 `/app/data/invite_access.db` 只保存邀请码/Cookie 哈希，和应用数据卷一起备份。原始邀请只保留在操作员指定文件。
- 没有公开创建邀请接口。访客不能修改模型连接、取得 API 密钥或执行管理员操作；意向单仍为测试数据，不涉及真实支付和发货。

## 验收范围

自动化测试覆盖 5 个并发独立登录、Cookie 刷新复用、身份/会话隔离、到期与持久撤销、跨站请求拒绝、WSS 已连接撤销、个人 Bearer 兼容及管理命令。此并发测试只验证登录隔离，不等于 5 路真实模型推理性能验收。公网 HTTPS、浏览器实际链路和云端发布需在部署后验收。
