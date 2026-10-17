# 20261017 Prompt 兼容升级准备补丁

此补丁用于当前生效版本 p-5ec7ab435e11c9a66b4e958dae74ec2e87eeb9fc21fa9491c9387a5320de7fc0，以及已构建的 20261017 后端镜像。代码指纹不符会停止。

prepare.sh 仅在发布目录生成候选文件，并只读检查生产注册表；不改生产数据、不重启服务。按镜像和服务器 .env 实际配置生成工具契约，避免网页搜索开关不一致。

在服务器当前发布目录执行：

```bash
tar -xzf /home/admin/ezbuying-prompt-repair-20261017.tar.gz
bash prompt-repair-20261017/prepare.sh
```

只有准备与只读预检通过后，才可选择已有的人工发布流程：

```bash
GLOBEX_CATALOG=abo GLOBEX_MANUAL_RELEASE=1 bash scripts/update_cloud.sh
```

此命令明确选择人工发布。真实模型成对评测尚未完成，记录为 evaluation_status=INCOMPLETE，不是上线质量门禁 PASS。仍执行来源、代码、正文和工具契约校验、停服备份、升级、启动、健康检查及 ABO 索引数量检查。不会删除 Prompt 注册表或重绑旧会话；旧会话如果工具契约变化可能需新建聊天。

成功后应看到 [5/5] Server responds，并核对运行前端包含 jump-to-latest，再在浏览器强制刷新验收。
