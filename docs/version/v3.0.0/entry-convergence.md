# 入口收敛登记（RT-015 产物）

> **上游**：`docs/version/v3.0.0/tasks/RT-015.md` §5 步骤 5、§8 AC6
> **状态**：RT-015 **收编本体已落地**（`chat_pipeline` 改由 `AgentLoop` 驱动，段序列来自 `foreground_chat` Profile）；**T-33 壳退役已落地（2026-10-09）**
> **登记口径**：`stream_chat` 的全部耦合点按「生产 / 转发门面 / 文档提及 / 测试」四类逐条登记，未登记项由 `tests/v30/test_runtime_foreground_cutover.py::TestEntryConvergence::test_entry_call_sites_registered` 守门

---

## 0. T-33 壳退役（2026-10-09）

`app/services/agent_service.py` 兼容壳**已删除**，`stream_chat` / `EmptyLLMResponseError` 收编至 `app/application/chat_pipeline.py`。

| 项 | 变更 |
|---|---|
| 壳文件 | `app/services/agent_service.py` **已删除**（`test_agent_service_shell_retired` 守门，禁止复活） |
| 入口实现 | `chat_pipeline.stream_chat(...)`（原壳逻辑逐字迁入：trace 兜底创建 + observability trace context set/reset） |
| Web 生产调用点 | `app/api/v1/chat.py` 改直连 `chat_pipeline.stream_chat` |
| 飞书生产调用点 | `app/channels/feishu/adapter.py` 改经 `app/application/channel_gateway.stream_chat` 转发（**R-7' 原则**：通道只依赖独立叶子门面，不直连 `chat_pipeline`） |
| 通道门面 | `channel_gateway` 新增 `stream_chat` / `EmptyLLMResponseError` 转发，取代原 `app.services.agent_service` 在 `channels` allowlist 中的位置 |
| 测试耦合 | 27 个测试文件的 `agent_service` 引用统一改为 `chat_pipeline`（别名）/ 模块级 `stream_chat` 打桩 |

---

## 1. 结论（收编后 + 壳退役后）

| 项 | 结论 |
|---|---|
| 壳是否退役 | **已退役**（T-33，2026-10-09）。原「保留」结论由本轮显式撤销 |
| 退役依据 | RT-015 §6 五条退役判据全部满足：① `AgentLoop` 驱动已落地（`test_single_loop_path`）；② 闭包测试全绿；③ 测试耦合点已迁移（别名过渡）；④ 生产 2 处调用点已改道；⑤ 本文件 §0 显式登记 |
| 是否存在未登记双入口 | 否。生产侧仅 2 处调用，全部经 `chat_pipeline.stream_chat`（Web 直连 / 飞书经 gateways 转发），无平行编排 |
| 收编本体 | **已落地**。`run_chat_pipeline` 内部由 `AgentLoop` + `foreground_chat` Profile 驱动；段序列只来自 `profiles.py`（`test_single_loop_path`） |

---

## 2. 生产调用点（2 处，全部登记）

| # | 位置 | 形态 | 去向（收编后） |
|---|---|---|---|
| P1 | `app/api/v1/chat.py:62` | `async for event in stream_chat(session_id, user_id, body.content, llm=llm, trace=trace)` —— Web SSE 装配 | 直连 `chat_pipeline.stream_chat`（经 `from app.application.chat_pipeline import stream_chat`）；**SSE 装配与错误映射零变化**（RT-015 §6.3 红线） |
| P2 | `app/channels/feishu/adapter.py:365` | `_consume_turn(...)` 内消费事件流（`kind == "token"` / `"done"`） | 经 `app.application.channel_gateway.stream_chat` 转发（R-7' 叶子门面）；飞书侧的 `EmptyLLMResponseError` 分支依赖异常外抛语义（见 §4 障碍 3） |

## 3. 转发门面与文档提及（非生产调用）

| 位置 | 性质 |
|---|---|
| `app/application/chat_pipeline.py:925` | `async def stream_chat(...)` **入口实现**：透传到 `run_chat_pipeline`，并负责 `trace` 兜底创建与 `observability` trace context 的 set/reset |
| `app/application/channel_gateway.py:21,25` | `stream_chat` **转发门面** + `EmptyLLMResponseError` 再导出（T-33 新增） |
| `app/application/agent_runtime/inbound.py:5,11` | docstring 提及（RT-013 明示「执行入口接管属 RT-015」） |
| `app/channels/feishu/adapter.py:219` | docstring 提及（RT-013 薄适配说明） |

## 4. 测试耦合点（T-33 已迁移）

### 4.1 直接调用（改为 `from app.application import chat_pipeline as agent_service` 或直连模块）

`tests/e2e/test_debug_*`（5 文件）· `tests/e2e/test_scene_cases.py` · `tests/e2e/test_trace_collector.py` ·
`tests/integration/test_observability_*`（3 文件）· `tests/integration/test_state_update_flow.py` ·
`tests/unit/test_llm_cost_gate.py` · `tests/unit/test_orchestration_v2.py` · `tests/v30/test_runtime_foreground_cutover.py` · `tests/v50/test_identity_cutover.py`

### 4.2 打桩替换（`monkeypatch.setattr(adapter, "stream_chat", …)` —— 原为 `adapter.agent_service`）

`tests/integration/test_feishu_adapter_turn.py`（7）· `tests/integration/test_feishu_cases.py`（2）·
`tests/integration/test_feishu_isolation.py`（1）· `tests/e2e/test_feishu_disabled.py`（1）·
`tests/unit/test_feishu_adapter_stream.py`（2）· `tests/unit/test_feishu_error_matrix.py`（2）

### 4.3 守护契约（T-33 同步更新）

| 守卫 | 变更 |
|---|---|
| `tests/unit/test_feishu_boundary.py` | allowlist 移除 `app.services.agent_service`（`channel_gateway` 原已在册） |
| `tests/v30/test_runtime_inbound_gateway.py` | `FORBIDDEN_IMPORTS` 中 `app.services.agent_service` → `app.application.chat_pipeline`（加强：gateway 不得依赖执行入口） |
| `tests/v30/test_runtime_outbound_gateway.py` | 同上 |
| `tests/v30/test_runtime_foreground_cutover.py` | `CALL_PATTERN` 改为 `(?<![\w.])stream_chat\s*\(`；守卫更名 `test_entry_call_sites_registered`；新增 `test_agent_service_shell_retired` |
| `tests/unit/test_chat_pipeline_split.py` | `test_agent_service_reexports_pipeline_symbols` → `test_agent_service_shell_retired` |

---

## 5. 收编本体技术障碍处置（已落地）

| # | 障碍 | 处置 |
|---|---|---|
| 1 | 前台段实现不存在 | `chat_pipeline` 内定义 9 个段实现，经 `AgentLoop(..., registry=…)` 按 Run 注入 |
| 2 | 流式 ↔ 段原语形态冲突 | `asyncio.Queue` 桥接：段内 `events.put`，驱动侧并发排空并 yield；`turn_meta` 在 `action_planning` 段末、首个 token 之前投递 |
| 3 | 循环吞异常与前台外抛语义冲突 | 段实现捕获并暂存 `stage_error`，循环收口后由 `run_chat_pipeline` 重新抛出 |
| 4 | `logical_clock` 绑定引入行为面 | 循环 `run()` 统一 bind/unbind；`_idle_seconds_since` 仍用 `datetime.now`，前台时间读取面不变 |
| 5 | `loop_runs.session_id` 前台未写入 | `open_foreground_run(user_id, session_id=session_id)` 同批补传 |
| 6 | 顺序体规模 | 拆为 9 个段实现 + 闭包状态载体；22 步本体函数逐段调用、零重写 |

---

## 6. 壳退役判据（RT-015 原判据 / T-33 已全部满足）

1. `chat_pipeline.run_chat_pipeline` 已由 `AgentLoop` 驱动，且段序列只来自 `profiles.py`（`test_single_loop_path` 通过）—— **✅**；
2. `tests/e2e` + `tests/golden` 全绿且与收编前基线逐项一致 —— **✅**；
3. §4.1 / §4.2 的测试耦合点已完成迁移或确认为「测试应直连新入口」—— **✅**（别名过渡 + 打桩点改 adapter 模块级）；
4. 生产 2 处调用点（P1 / P2）改为直连 `run_chat_pipeline` —— **✅**（Web 直连；飞书经 `channel_gateway` 叶子门面转发，符合 R-7'）；
5. 退役提交需在验收报告中显式登记（`baseline §9 P2` 技术债结清）—— **✅**（本文档 §0）。
