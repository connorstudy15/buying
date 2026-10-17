# 购物需求识别与确认

## 方案与交互

复用现有 Agent 工具、A2UI shopping-v2 协议、ShoppingFormStore 和提交后继续对话的链路。
新增 `show_shopping_requirements`，由 Main Agent 根据当前自然语言和会话上下文生成需求卡。
多条件的新选购目标、用户主动要求整理/修改需求时生成卡片；前端也提供“整理并确认需求”按钮。
简单单条件搜索、纯知识问答、订单查询继续原流程。

1. Agent 提取选购目标及相关预算、用途、电脑尺寸、重量、排除条件等。
2. 每项展示 `extracted`（已提取）、`inferred`（AI 推测）或 `unknown`（尚未明确），提交前均待确认。
3. 已提取项附用户原话，硬性条件与偏好单独标示。未知项留空，无固定品类题库。
4. 用户直接编辑、清空或补充，点击“确认需求并继续选购”。
5. 服务端按持久字段定义校验，保存最终答案，并生成同会话下一轮输入。
6. Agent 使用已确认答案继续检索；未回答项仍未知，不重复展示相同确认卡。

## 数据合同

工具入参示例：

```json
{
  "title": "通勤背包需求",
  "context": "选择通勤背包",
  "fields": [
    {"id":"goal","label":"想买什么","value":"通勤背包","status":"extracted","source_quote":"想买个通勤背包","constraint_kind":"unspecified"},
    {"id":"budget","label":"预算","value":"500元以内，含税运范围未说明","status":"extracted","source_quote":"500元以内","constraint_kind":"hard"},
    {"id":"laptop_size","label":"电脑尺寸","status":"unknown"},
    {"id":"weight","label":"重量偏好","value":"尽量轻","status":"extracted","source_quote":"尽量轻","constraint_kind":"preference"}
  ]
}
```

字段值使用有边界的文本，保留“不超过”“左右”“单件/总价”“币种未明确”等自然语言限定；
不强行把模糊预算和重量转换成硬数值。检索仍由现有工具参数和领域规则校验。
用户改写字段后，旧 constraint_kind 不再自动沿用，交由 Agent 按新表达解释。
原话由模型提取、供用户核对，不代表服务器已经验证其与全部聊天历史逐字一致。

确认结果包含 `requirements_confirmed`、`answers`、`requirements` 和 `unanswered`。
确认后去除旧 agent_context，避免用户清空的条件从背景重新进入提示词。
复用买家/会话归属校验、版本检查、幂等 request_id、SQLite 持久化和恢复。
确认只用于本次购物；不创建订单，也不写长期偏好。

## 代码位置

- `app/application/tools/shopping_requirements_tool.py`：需求提取工具合同与卡片事件。
- `app/infrastructure/shopping_forms.py`：字段校验、持久化与确认消息。
- `app/application/agents/main_agent.py`：注册工具及触发规则。
- `frontend/src/components/ShoppingForm.tsx`：需求卡编辑、状态、原话与确认。
- `frontend/src/App.tsx`：主动整理需求入口。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_shopping_requirements.py tests/test_shopping_forms.py -q
cd frontend
npm.cmd test -- --run tests/shoppingForm.test.tsx
npm.cmd run build
```

后端覆盖校验、清空/修改、持久恢复、跨买家拒绝、重复提交以及 AgentScope 工具调用 →
AG-UI 卡片投影 → 确认消息回到模型上下文。Agent 集成测试使用确定性模拟模型。
前端覆盖状态/来源展示、修改清空、空卡拒绝、确认提交及旧澄清表单兼容。
需要重启后端加载新的工具注册与提示词；生产前端需部署重新构建的文件。
