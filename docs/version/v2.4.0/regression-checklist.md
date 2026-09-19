# V2.4.0 Tool System 人工回归清单

> 上游：[tool-system/architecture.md](./tool-system/architecture.md)（§5 执行器五段、§6 权限闸、§7 工具面）、[tasks/](./tool-system/tasks/)（TOOL-001~012）
> 用途：真实模型环境下的人工验收执行单；每条含 **前置 / 操作 / 期望 / 观测点**。
> 状态：待执行（执行结论回写本文件末尾「执行记录」区）。
> 配套自动化：`apps/backend/tests/v24/`（TOOL-001~012，1456 用例）+ `tests/v26/`（执行域统一分派 / 确认登记 / 短路映射）。
>
> **口径说明（vXX_ 开关体系收官，2026-09-19）**：原 10 个 v24 Flag 已删除，工具系统**常开**；
> 行动域经裁决 B 采用「工具绑定优先路由」——凡能解析出工具绑定的动作（含 internal 类）
> 一律经工具五段（权限→确认→校验→调用→归一）执行。本清单按收官后语义编写，
> 历史文档中的「总闸 / 子闸 / 启用链」表述视为 V2.4.0 设计期坐标。

---

## 1. 环境准备

| 项 | 说明 |
|---|---|
| Flag 状态 | 无需配置（工具系统常开，`v24_*` Flag 已随开关体系删除；遗留 env 键会被启动告警或静默忽略） |
| 基闸要求 | `ACTION_ENABLED=true`（行动域总闸，非版本号 Flag）；世界写验证需 `WORLD_ENABLED=true` |
| 通道工具 | 飞书通道工具（`channel.feishu.send`）需要 `FEISHU_ENABLED=true` + APP_ID/APP_SECRET/VERIFICATION_TOKEN |
| 内置工具 | `register_builtin_tools` 启动自动注册：`builtin.reminder.*` / `builtin.memory.save` / `builtin.search.query` / `world.env.query` / `world.object.*` / `builtin.notification.send`（sensitive）/ `channel.feishu.send`（sensitive，随通道启用） |
| 调试端点 | `GET /api/v1/debug/tools/*`（清单 / 面投影 / 权限快照）与 `GET /api/v1/debug/action-execution/*`（actions / schedules / metrics）**恒可见**（无 404 门控） |
| 观测三件套 | ① 调试端点 JSON ② `action_records.steps[]`（`tool_id` / `permission` / `validation` / `result` / 脱敏 params）③ 库断言（下节 SQL） |

库断言速查：

```sql
-- 动作台账与短路终态
SELECT id, action_type, status, gate_reason, attempt, next_retry_at FROM action_records
 WHERE user_id=:u ORDER BY created_at DESC LIMIT 20;
-- 确认请求（trigger_registry 承载）
SELECT trigger_key, payload->>'tool_id' AS tool_id, payload->>'status' AS status
  FROM trigger_registry WHERE payload->>'kind' = 'tool_confirmation' ORDER BY created_at DESC;
-- 确认请求与授权 grant（同表 trigger_registry，payload.kind 区分）
SELECT trigger_key, payload->>'tool_id' AS tool_id, payload->>'kind' AS kind,
       payload->>'scope' AS scope, payload->>'expires_at' AS expires_at
  FROM trigger_registry
 WHERE user_id=:u AND payload->>'kind' IN ('tool_confirmation','tool_grant')
 ORDER BY created_at DESC;
-- outbox 世界写（唯一写路径）
SELECT id, action_id, idempotency_key, status FROM outbox_events
 WHERE user_id=:u ORDER BY created_at DESC LIMIT 10;
```

---

## 2. 权限面（最高优先：转真实授权判定）

### R-2.1 safe 工具免授权直通
- **前置**：默认环境（无 grant）。
- **操作**：触发一次 `query_environment`（天气/环境查询）或 `remember_fact`。
- **期望**：`steps[0].permission.decision == "allow"`、`reason == "level_no_grant_required"`；动作直接执行成功，无确认话术。
- **观测点**：`action_records.steps[0]`；`GET /api/v1/debug/action-execution/actions`。

### R-2.2 sensitive 工具首次调用 → 确认登记（零外呼）
- **前置**：默认环境（`builtin.notification.send` 为 sensitive + confirm=first_time）。
- **操作**：让角色发一条通知（触发 `send_notification` 意图）。
- **期望**：`record.status == "planned"`、`gate_reason == "pending_confirmation"`；`steps[0].status == "skipped"`；**能力零调用**；确认话术（角色语气、以问句收尾）进入回复素材与 `record.result.error`；`trigger_registry` 出现一条 pending 确认行，`dedupe_key` 与 record 一致。
- **观测点**：库断言两条；下一轮回复文本含话术。

### R-2.3 批准轮：原记录恢复 + grant 落地 + 二次调用免确认
- **前置**：R-2.2 的 pending 态。
- **操作**：用户回复「好 / 可以 / 发吧」（确认意图词表命中）。
- **期望**：**同一 ActionRecord**（不产生第二条）从 planned 恢复执行并成功；`session_id` 保留；工具收到与首次**相同的 params 与 dedupe_key**；`permission_grants` 落一条 `source='user_confirm'`、`scope=('self',)` 的 grant；随后**第二次**同类通知不再确认（grant 命中，`decision == "allow"`、`reason == "grant_matched"`）。
- **观测点**：`list_records` 计数不变；grant SQL；第二次调用的 `steps[0].permission`。

### R-2.4 否定轮与过期轮
- **操作**：① 对 pending 请求回复拒绝语；② 构造一条过期 pending（DB 把 `expires_at` 改到过去）后回复批准。
- **期望**：① record → `cancelled` / `gate_reason=permission_denied`，能力零调用，pending 清空；② 不执行，record → cancelled，request → `expired`。
- **观测点**：库断言；能力调用打桩计数（自动化已覆盖，人工抽查回复文本）。

### R-2.5 不受信命名空间拒绝
- **操作**：注册一个 `user.*` 命名空间的工具定义（或用现有 `user.*` 声明），触发对应意图。
- **期望**：`steps[0].permission.decision == "deny"`、`reason == "untrusted_namespace"`；record → `cancelled` / `permission_denied`；能力零调用；不产生确认请求。
- **观测点**：`steps[0].permission`；pending SQL 为空。

### R-2.6 敏感参数脱敏
- **前置**：工具定义声明 `sensitive` 参数（如 recipient）。
- **操作**：执行一次携带敏感参数的工具调用。
- **期望**：`action_records.steps[0].params` 中敏感值为 `***`（**台账脱敏**，实际调用入参不脱敏）。
- **观测点**：steps[0].params vs 工具收到的实参（打桩）。

---

## 3. 工具绑定优先路由（裁决 B：internal 动作同样过五段）

### R-3.1 提醒类动作端到端
- **操作**：对话中让角色「设一个明早八点的提醒」。
- **期望**：`create_reminder` 经 `builtin.reminder.create` 五段执行；`steps[0].tool_id == "builtin.reminder.create"`、`capability == "reminder"`；提醒落库且 due 校验通过（未来时间）；`record.status == "succeeded"`。
- **观测点**：steps[0]；提醒表；`/debug/action-execution/metrics` 的 success_rate。

### R-3.2 世界对象移动经 outbox 延迟投递（唯一写路径）
- **前置**：世界已启用，场景内有对象（如「牛奶」在家）。
- **操作**：让角色「把牛奶拿到厨房」；**在 outbox 消费前**查对象位置。
- **期望**：动作 `succeeded` 但对象位置**尚未变化**（工具只投递 `deferred_world_op`）；outbox 消费器执行后位置变为「厨房」；`world_engine` 的直接世界写调用方不含工具层（自动化静态钉测）。
- **观测点**：`outbox_events` 行；消费前后 `object_location`；重放（同 idempotency_key 再消费）不重复落库。

### R-3.3 工具记忆沉淀边界
- **操作**：执行一次 `remember_fact`（工具记忆边界表「deposit」类）与一次 `query_environment`（读类）。
- **期望**：前者按边界表沉淀记忆（幂等：同 effect 不重复沉淀）；后者**零沉淀**。
- **观测点**：`memories` 表新增行与 `source_ref`；读类动作后 memories 无变化。

---

## 4. 校验 / 观测 / 健康

### R-4.1 语义校验拒绝（invalid）
- **操作**：触发一个带过期 `due_at` 的提醒意图。
- **期望**：校验段拒绝 → record `cancelled` / `invalid_params`；`steps[0].result.payload.failure_kind == "invalid"`；能力零调用；**不重试**。
- **观测点**：steps[0].result；`next_retry_at` 为空。

### R-4.2 熔断与冷却
- **操作**：连续打挂同一工具 ≥ `TOOL_BREAKER_THRESHOLD`（默认 3）次。
- **期望**：熔断打开 → 后续调用 `unavailable` 短路（record cancelled / capability_unavailable）；冷却窗过后半开恢复。
- **观测点**：`/debug/tools` 的 health 投影；steps[0].result.status。

### R-4.3 能力超时归一
- **操作**：注入一个慢能力（或等真实超时）。
- **期望**：`CapabilityResult.timeout` → `ToolResult.status="timeout"` → ActionResult `status="timeout"`、`failure_kind="timeout"`；按重试策略退避（permanent 不重试）。
- **观测点**：steps[0].result；`next_retry_at` 非空（可重试时）。

---

## 5. 工具面 / 额度 / 调试面

### R-5.1 工具面投影随 Run Profile 裁剪
- **操作**：分别在前台对话与自治 tick 中触发规划。
- **期望**：前台投影含 `channel.*`（通道启用时），自治 tick 不含（`tool_facts` 无 channel 工具）；`surface_hash` 同输入稳定。
- **观测点**：`/debug/tools` 面投影；decision `input_snapshot.tool_facts`。

### R-5.2 额度不被工具路径放宽
- **操作**：`AUTONOMY_ACTION_DAILY_LIMIT=1` 下连续触发两次自治动作。
- **期望**：第二次被额度拒绝；计划步（plan 来源）与主动动作共用同一额度口径。
- **观测点**：decision `gate_reason`；action_records 计数。

### R-5.3 调试面恒可见 + 只读
- **操作**：直接访问 `/debug/tools*` 与 `/debug/action-execution/*` 六端点。
- **期望**：全部 200（无 404 门控）；会话级写探针确认零写入（只读纪律）。
- **观测点**：状态码；调试端点响应形状（plans 面字段契约同 v2.5.0 清单 D 系列）。

---

## 6. 扩展通道（external / user.* 声明面）

### R-6.1 外部 API 保留位
- **操作**：构造一个无法解析出工具绑定的 external 类动作（或移除其绑定声明）。
- **期望**：按保留位语义失败（`external_adapter_reserved` / unavailable），不产生半完成状态；失败只 log 不回滚计划终态。
- **观测点**：record.gate_reason；日志。

### R-6.2 扩展工具清单加载
- **前置**：`TOOL_EXT_MANIFEST_PATH` 指向合法 manifest、`TOOL_EXT_ALLOWED_HOSTS` 配置。
- **操作**：重启加载扩展工具；随后注入一个语法错误的 manifest。
- **期望**：合法清单注册生效（`/debug/tools` 可见）；错误 manifest 记日志但不中断启动（E3）。
- **观测点**：`/debug/tools`；启动日志。

---

## 执行记录

> 执行人 / 日期 / 环境（模型、库、分支 HEAD）/ 逐条结论（✅ / ❌ + 现象）/ 遗留问题。
>
> | 日期 | HEAD | 环境 | 结论 |
> |---|---|---|---|
> | （待填） | | | |
