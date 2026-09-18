# V2.4.0 Tool System 人工回归清单（ACCEPTANCE-CHECKLIST）

> **上游依据**：[architecture.md](../../../../docs/version/v2.4.0/tool-system/architecture.md) §11.4（版本验收 Gate）、§9.5（安全不变量）、§7.8（Flag 设计）；[tasks/TOOL-012](../../../../docs/version/v2.4.0/tool-system/tasks/TOOL-012.md)
> **定位**：真实模型 / 真实通道环境下的人工验收执行单。
> **配套自动化**：`apps/backend/tests/v24/test_tool_acceptance.py`、`test_tool012_bans.py`、`test_tool012_scenarios.py`（CI 可跑的全部结构面与不变量）。
> **互补原则**：本清单**只保留必须由真实模型或真实外部通道才能判定的条目**；凡自动化已断言的结构、Flag 矩阵、静态扫描、政策闸、确认状态机条目一律不在本清单重复（避免"文档断言与测试断言重叠"）。
> **状态**：待执行（执行结论回写文末「执行记录」区）。
> **落位说明（偏移登记）**：TOOL-012 原计划产出 `docs/version/v2.4.0/tool-system/regression-checklist.md`；本次按用户级约束「不改文档」改落至本路径，`docs/` 零改动。

---

## 1. 环境准备与基线取证

| 项 | 说明 |
|---|---|
| Flag 基线 | 全部 `V24_TOOL_*` 默认 off；按 §7.8 启用链逐组开启（总闸 → 子闸），每组观察后再开下一组 |
| 启用顺序 | `V24_TOOL_SYSTEM_ENABLED` → `V24_TOOL_SCHEMA_VALIDATION_ENABLED` → `V24_TOOL_PERMISSION_ENABLED` → `V24_TOOL_OBSERVATION_ENABLED` → `V24_TOOL_SURFACE_ENABLED` → `V24_TOOL_MEMORY_ENABLED` → `V24_TOOL_REFLECTION_ENABLED` → `V24_TOOL_EXTERNAL_API_ENABLED` → `V24_TOOL_USER_DEFINED_ENABLED` → `V24_TOOL_CHANNEL_ENABLED`（另需 `FEISHU_ENABLED=true` + 三项飞书凭据） |
| 调试端点 | `GET /api/v1/debug/tools`、`/tools/surface`、`/tools/executions`、`/tools/permissions`、`/tools/confirmations`、`/tools/manifests`、`/tools/external`、`/tools/user-defined`、`/tools/{tool_id}`；`POST /debug/tools/{tool_id}/disable`、`/enable`、`/permissions/revoke`、`/confirmations/{request_id}/revoke` |
| 观测三件套 | ① 调试端点 JSON ② `runtime_traces` 的 `autonomy_tool_surface` / 第 9 步步骤 ③ 库断言（下节 SQL） |
| 内存 SQLite | 自动化侧全部离线可跑；人工侧建议用真实 PG，避免方言差异掩盖问题 |

库断言速查（SQLite / PG 通用）：

```sql
-- 工具执行台账（唯一落点：action_records.steps）
SELECT id, action_type, status, gate_reason,
       json_extract(steps, '$[0].tool_id')            AS tool_id,
       json_extract(steps, '$[0].permission.decision') AS perm_decision,
       json_extract(steps, '$[0].result.status')       AS result_status
  FROM action_records WHERE user_id = :u ORDER BY created_at DESC LIMIT 20;

-- 待确认请求 / 授权（复用 trigger_registry，无新表）
SELECT trigger_key, trigger_type, due_at, payload FROM trigger_registry
 WHERE user_id = :u AND trigger_type IN ('action_due') ORDER BY due_at DESC;

-- 世界事件唯一 SoT + 延迟投递
SELECT type, title, source, idempotency_key,
       json_extract(payload, '$.outbox_action_id') AS outbox_action_id
  FROM world_events WHERE world_id = :w ORDER BY created_at DESC LIMIT 30;
SELECT idempotency_key, status, payload FROM outbox_events
 WHERE status <> 'consumed' ORDER BY created_at DESC LIMIT 20;
```

### 基线取证（G-COMPAT 逐字节比对的可复现步骤，只读、不覆盖工作区）

V2.3.0 基线提交 = `d67ebe7`（V2.4.0 文档提交 `78854d5` 的父提交；仓库无 tag）。

```bash
# ① 检出 V2.3.0 的 app 树到仓库外临时目录（只读，不写工作区）
git archive --format=tar d67ebe7 apps/backend/app | tar -x -C "$TMPDIR/tool012/v230"
# ② 用仓库 venv 渲染同一组确定性输入（脚本见 test_tool_acceptance.py 顶部 docstring 的
#    render_acceptance_artifacts 等价实现），V2.3.0 与 V2.4.0 各出一份 JSON
# ③ 逐字节比较
python - <<'PY'
import json, hashlib
a = json.load(open("$TMPDIR/tool012/art_v230.json", encoding="utf-8"))["artifacts"]
b = json.load(open("$TMPDIR/tool012/art_v240.json", encoding="utf-8"))["artifacts"]
assert set(a) == set(b)
for key in sorted(a):
    assert a[key] == b[key], key
print("ALL_ARTIFACTS_BYTE_IDENTICAL", len(a))
PY
```

自动化侧等价断言（离线、无需 git）：`test_g_compat_prompt_artifacts_match_checked_in_v230_golden`（对 `tests/golden/*.txt`）、`test_g_compat_reflection_prompt_matches_v230_literal`、`test_g_compat_frozen_blobs_zero_diff`（git blob 对象口径）；若存在仓库外基线产物（`TOOL012_BASELINE_ARTIFACTS` 或仓库同级 `tool012-baseline/artifacts_v230.json`），`test_g_compat_artifact_bundle_matches_git_archive_baseline` 会做全量 6 产物比对，否则 skip。

---

## 2. 前台工具调用与结果呈现（需真实模型）

### R-2.1 创建提醒的自然语言召回

- **id**：`R-2.1`
- **前置**：总闸 on；`ACTION_ENABLED=true`；真实 chat 模型可用。
- **步骤**：前台对话输入「明天早上九点提醒我开会」。
- **期望**：出现 1 条 `action_records`（`action_type=create_reminder`、`status=succeeded`），`steps[0].tool_id=builtin.reminder.create`；回复以角色口吻确认，且未出现系统公告腔。
- **观测点**：`/debug/tools/executions?user_id=`；`world_events` 出现 `type=reminder`。
- **关联任务**：TOOL-002 / TOOL-005。

### R-2.2 工具结果的观察键进入回复素材

- **id**：`R-2.2`
- **前置**：总闸 + `V24_TOOL_OBSERVATION_ENABLED=true`；真实模型。
- **步骤**：输入「现在外面天气怎么样」。
- **期望**：回复引用环境事实（天气/时段），而非泛泛而谈；`steps[0].result.observations` 含 `env.weather` 或 `env.part_of_day`。
- **观测点**：`action_records.steps[0].result.observations`；prompt trace 第 9 步素材。
- **关联任务**：TOOL-003 / TOOL-005。

### R-2.3 工具不可用时的降级表达

- **id**：`R-2.3`
- **前置**：总闸 on；检索源未配置（默认态）。
- **步骤**：输入「帮我搜一下这件事」。
- **期望**：不出现崩溃或空回复；`builtin.search.query` 不在默认工具面内（`/debug/tools/surface` 的 `excluded` 含 `unavailable:source_not_configured`）；角色以"暂时查不到"的方式回应。
- **观测点**：`/debug/tools/surface`、回复文本。
- **关联任务**：TOOL-004 / TOOL-010。

---

## 3. 参数校验与追问（需真实模型）

### R-3.1 语义失败后的补问而非硬失败

- **id**：`R-3.1`
- **前置**：总闸 + 校验闸 on；真实模型。
- **步骤**：输入「提醒我一下」（无时间）。
- **期望**：不落失败台账；角色追问具体时间（一次只问一个问题）。
- **观测点**：`action_records`（应无 `gate_reason=invalid_params` 的失败行或仅 1 行且被追问覆盖）。
- **关联任务**：TOOL-003。

### R-3.2 非法时间被拦下且话术可读

- **id**：`R-3.2`
- **前置**：同 R-3.1。
- **步骤**：输入「提醒我昨天下午三点开会」。
- **期望**：`due_at` 因 `not_future` 被拦，`steps[0].status=invalid`；回复不含“已设置提醒”。
- **观测点**：`action_records.steps[0].validation.semantic[].code`。
- **关联任务**：TOOL-003。

---

## 4. 权限与确认流（需真实模型 + 真实通道）

### R-4.1 首次外发确认的完整闭环

- **id**：`R-4.1`
- **前置**：总闸 + 权限闸 + 通道闸 on；`FEISHU_ENABLED=true` 且绑定完成；真实模型。
- **步骤**：① 让角色给绑定用户发一条消息 → ② 回复「好」/「可以」→ ③ 再次要求发同类消息。
- **期望**：① 本轮**零外发**，回复为角色语气确认话术（非公告），`trigger_registry` 出现待确认行；② 外发 1 条且 `OutboundMessage.idempotency_key` 与原 `dedupe_key` 一致；③ 第二次在 TTL 内直接外发（不再重复确认）。
- **观测点**：`/debug/tools/confirmations`、飞书侧实收消息、`outbox_events`。
- **关联任务**：TOOL-005 / TOOL-010。

### R-4.2 否定与过期

- **id**：`R-4.2`
- **前置**：同 R-4.1。
- **步骤**：① 生成确认请求后回复「不用了」；② 另生成一次请求后 24h 内不作回应。
- **期望**：① 请求置终态、零外发、不留长期 grant；② TTL 到期由维护步置 expired、零外发。
- **观测点**：`/debug/tools/confirmations`（消失/状态）、`trigger_registry` 状态。
- **关联任务**：TOOL-005。

### R-4.3 收件人不在授权名单

- **id**：`R-4.3`
- **前置**：同 R-4.1；仅授权 A，要求发给 B。
- **步骤**：要求给未授权联系人发消息。
- **期望**：`out_of_scope` / `recipient_not_authorized` 拒绝路径，零外发，角色以"没有授权"回应而非静默失败。
- **观测点**：`steps[0].permission.reason`、回复文本。
- **关联任务**：TOOL-003 / TOOL-005。

### R-4.4 域名白名单的真实拒绝（需真实外部 API）

- **id**：`R-4.4`
- **前置**：总闸 + 外部 API 闸 on；`V24_TOOL_EXT_MANIFEST_PATH` 指向真实清单；`V24_TOOL_EXT_ALLOWED_HOSTS` 配置真实域名。
- **步骤**：① 正常调用白名单内域名；② 用一个不在白名单的 host 触发调用。
- **期望**：① 成功并把响应映射进 observations 且带 `ext.untrusted=true`；② `denied / host_not_allowed`，且**无任何出站请求**。
- **观测点**：`/debug/tools/external`、出站抓包或上游访问日志。
- **关联任务**：TOOL-011。

---

## 5. 自治工具调用（需真实模型 tick）

### R-5.1 自治 tick 的工具面与三账对齐

- **id**：`R-5.1`
- **前置**：`ACTION_ENABLED=true` + `AUTONOMY_ACTION_ENABLED=true` + 总闸 on；真实模型；存在持久目标与闲置会话。
- **步骤**：跑一次真实 life-loop tick（或等待调度）。
- **期望**：`runtime_traces` 出现 `autonomy_tool_surface` 步骤，其 `tool_ids` 不含 `channel.*`；Run 台账 / 决策台账 / 行动台账三账 user_id 一致；工具面内的工具能产出可解释的自治意图。
- **观测点**：`loop_runs`、`decision_records.input_snapshot.tool_facts`、`action_records`。
- **关联任务**：TOOL-006 / TOOL-007。

### R-5.2 工具面收窄不导致空转

- **id**：`R-5.2`
- **前置**：同 R-5.1；相对阶段设为 `stranger`，语境设为 `late_night`。
- **步骤**：同一输入分别在 `foreground_chat` 与 `autonomous_tick` 下跑。
- **期望**：两侧投影出不同工具面且 `surface_hash` 可复现；自治侧永不投放通道类工具；前台侧在深夜不投放社交类工具。
- **观测点**：`/debug/tools/surface?run_kind=...`。
- **关联任务**：TOOL-004 / TOOL-006。

---

## 6. 通道工具专项（需真实飞书）

### R-6.1 长消息切分与幂等

- **id**：`R-6.1`
- **前置**：通道闸 on；真实飞书。自动化侧只能覆盖 200 字上限内的样例。
- **步骤**：发送一条 >600 字的消息。
- **期望**：飞书侧按序收到多条，逐条内容拼接后与原文**逐字节相同**；重放同一 `dedupe_key` 不产生第二条。
- **观测点**：飞书实收消息、`channel_identity` 绑定侧记录。
- **关联任务**：TOOL-010。

### R-6.2 通道错误码映射的真实表现

- **id**：`R-6.2`
- **前置**：通道闸 on；真实飞书（可构造错误场景：失效 token / 无权限接收人 / 限频）。
- **步骤**：分别触发 auth / not_found / rate_limited。
- **期望**：`steps[0].result.failure_kind` 分别为 `permanent` / `permanent` / `transient`；角色话术与失败类型匹配（限频可重试而非"永久失败"）。
- **观测点**：`action_records.steps[0].result`。
- **关联任务**：TOOL-010。
- **说明（E5）**：`ChannelErrorKind` 全部 9 个取值的映射表已由 `test_s8_channel_error_maps_to_failure_kind` 在自动化侧断言；本条只判"真实通道下的话术与重试表现"。

---

## 7. 记忆分层与反思（需真实模型）

### R-7.1 读类工具零沉淀的真实观察

- **id**：`R-7.1`
- **前置**：总闸 + 记忆闸 on；真实模型。
- **步骤**：连续 5 轮只读查询（天气/时段/地点）。
- **期望**：`memories` 零新增；`/debug/tools/executions` 中这些调用的 `effects` 不含 `kind=memory`。
- **关联任务**：TOOL-008。

### R-7.2 反思证据窗的语义质量

- **id**：`R-7.2`
- **前置**：反思子闸 on；真实模型；已有 ≥ 阈值条同工具失败记录。
- **步骤**：跑一次反思触发。
- **期望**：产出的 Insight 类型落在 `capability_note` / `usage_preference` / `interaction_calibration` 三类内，且**不出现**性格 / 人格 / 关系类结论；工具状态未被自动修改。
- **观测点**：`insights`（type / scope）、`/debug/tools`（工具状态与健康度不变）。
- **关联任务**：TOOL-009。

---

## 8. 扩展性实操（需人工动手 + 真实模型）

### R-8.1 新增内置工具的 4 步实操

- **id**：`R-8.1`
- **前置**：开发环境；基线 `d67ebe7` 可用。
- **步骤**：按 architecture §10.1 的四步新增一个内置工具（声明 → 复用实现 → 注册一行 → 资产文案），不改管线文件。
- **期望**：`git diff --name-only` 命中 ≤ 4 个文件，且**不含** `planner.py` / `decision_pipeline.py` / `chat_pipeline.py` / `post_process.py` / `action_engine.py` / `autonomy_engine.py` / `prompts/`；新增工具可被 `/debug/tools` 列出并经真实模型调用成功。
- **关联任务**：TOOL-002 / TOOL-012（G-EXTEND）。

### R-8.2 新增外部 API 工具的 1 个 YAML 实操

- **id**：`R-8.2`
- **前置**：外部 API 闸 on；真实第三方 API 与其凭据（**只经环境变量**）。
- **步骤**：新增一个 manifest YAML → 配 `V24_TOOL_EXT_ALLOWED_HOSTS` → 跑真实调用。
- **期望**：零 Python 改动；`/debug/tools/manifests` 显示 `loaded`；凭据不出现在任何日志 / 端点 / 台账。
- **关联任务**：TOOL-011。

### R-8.3 用户自定义工具的注册与拒绝

- **id**：`R-8.3`
- **前置**：总闸 + 自定义工具闸 on；真实模型。
- **步骤**：① 注册一个合法声明（如"每天记录一句心情"）；② 提交一个携带任意代码 / URL 的声明。
- **期望**：① 注册成功、首次使用需确认、默认不沉淀记忆；② 被 DSL 红线拒绝且不留下任何注册痕迹。
- **关联任务**：TOOL-011。

---

## 9. 零迁移、回退与文档一致性

### R-9.1 全 Flag 回退到 V2.3.0 行为

- **id**：`R-9.1`
- **前置**：V2.4.0 全 off 的部署。
- **步骤**：跑一段常规前台对话 + 一轮自治 tick。
- **期望**：prompt 文本与 V2.3.0 逐字节一致（对 `tests/golden/*.txt`）；行为路径不出现 `tool_id` / `permission` 等新键；无任何工具系统调试端点可见（`enabled=false` 或 403）。
- **关联任务**：TOOL-001 / TOOL-012（G-COMPAT）。

### R-9.2 0046 迁移的升降级往返（需真实 PG）

- **id**：`R-9.2`
- **前置**：PostgreSQL 可用（`TEST_DATABASE_URL`）；`alembic upgrade head` 已到 0045。
- **步骤**：`alembic upgrade head`（→ 0046）→ 写入一条 `capability_note` Insight → `alembic downgrade 0045` → 再 `upgrade head`。
- **期望**：升级后三类新 Insight 类型可写；降级后旧值域恢复且**既有 belief/preference/pattern 数据零丢失**；再升级不报错。
- **关联任务**：TOOL-009 / TOOL-012（零迁移最终核对）。
- **说明**：自动化侧只断言迁移链 head 与 0046 的 downgrade 实现存在（内存 SQLite 无法覆盖 PG 原生 DROP CONSTRAINT 路径）。

### R-9.3 版本事实回写核验（人工，不改 docs）

- **id**：`R-9.3`
- **前置**：无。
- **步骤**：核对 architecture §5.1 与 tasks.md 是否已记录「零迁移断言破例一次（0046、值域放宽、可降级）」。
- **期望**：文档已记录；未记录时由负责人在**后续文档任务**中回写（本次验收不修改 `docs/`）。
- **关联任务**：TOOL-009 / TOOL-012。

---

## 10. Gate 判定汇总（自动化已可判定，此处仅登记结论）

| Gate | 判定手段 | 结论 |
|---|---|---|
| G-COMPAT | `test_g_compat_*`（8 例）+ 本清单 §1 基线取证 | PASS |
| G-GOVERN | `test_g_govern_*`（2 例） | PASS |
| G-SELECT | `test_g_select_*`（4 例） | PASS |
| G-VALIDATE | `test_g_validate_*`（15 例） | PASS |
| G-PERMISSION | `test_g_permission_*`（3 例）+ 不变量 1/2 | PASS |
| G-WORLD | `test_g_world_*`（2 例）+ S5 | PASS |
| G-MEMORY | `test_g_memory_*`（6 例）+ S6 | PASS |
| G-EXTEND | `test_g_extend_*`（3 例）+ 本清单 §8 实操 | PASS（半自动：实操记录待填） |

---

## 11. 执行记录

| id | 执行人 | 日期 | 环境（模型 / 通道） | 结果 | 备注 |
|---|---|---|---|---|---|
| R-2.1 | | | | | |
| R-2.2 | | | | | |
| R-2.3 | | | | | |
| R-3.1 | | | | | |
| R-3.2 | | | | | |
| R-4.1 | | | | | |
| R-4.2 | | | | | |
| R-4.3 | | | | | |
| R-4.4 | | | | | |
| R-5.1 | | | | | |
| R-5.2 | | | | | |
| R-6.1 | | | | | |
| R-6.2 | | | | | |
| R-7.1 | | | | | |
| R-7.2 | | | | | |
| R-8.1 | | | | | |
| R-8.2 | | | | | |
| R-8.3 | | | | | |
| R-9.1 | | | | | |
| R-9.2 | | | | | |
| R-9.3 | | | | | |
