# 入口收敛登记（RT-015 产物）

> **上游**：`docs/version/v3.0.0/tasks/RT-015.md` §5 步骤 5、§8 AC6
> **状态**：本轮为 RT-015 **前置切片**（契约冻结 + 入口登记）；收编本体（`chat_pipeline` 改由 `AgentLoop` 驱动）尚未落地
> **登记口径**：`agent_service.stream_chat` 的全部耦合点按「生产 / 壳本体 / 文档提及 / 测试」四类逐条登记，未登记项由 `tests/v30/test_runtime_foreground_cutover.py::test_agent_service_call_sites_registered` 守门

---

## 1. 结论（本轮）

| 项 | 结论 |
|---|---|
| 壳是否退役 | **保留**。本轮不退役 `app/services/agent_service.py` 的 `stream_chat` 符号 |
| 保留理由 | ① 收编本体未落地，壳仍是唯一前台执行入口；② 17 个测试文件直接调用该符号、6 个文件以 `monkeypatch.setattr(agent_service, "stream_chat", …)` 打桩，**测试耦合面 33 处**，退役必须与收编同批完成，否则测试夹具需全体重写；③ RT-015 §3.2 明确「不删除 `agent_service`（除非调用点全部迁移完毕且登记完成）」 |
| 是否存在未登记双入口 | 否。生产侧仅 2 处调用，且都指向同一条 `run_chat_pipeline` 链路（壳是唯一实现，无平行编排） |

---

## 2. 生产调用点（2 处，全部登记）

| # | 位置 | 形态 | 去向（收编后） |
|---|---|---|---|
| P1 | `app/api/v1/chat.py:50` | `async for event in agent_service.stream_chat(session_id, user_id, content, llm=llm, trace=trace)` —— Web SSE 装配 | 直连 `chat_pipeline.run_chat_pipeline`（跳过壳），或保留壳作为唯一入口；**SSE 装配与错误映射零变化**（RT-015 §6.3 红线） |
| P2 | `app/channels/feishu/adapter.py:365` | `_consume_turn(...)` 内消费事件流（`kind == "token"` / `"done"`） | 同 P1；飞书侧的 `EmptyLLMResponseError` 分支依赖异常外抛语义（见 §4 障碍 3） |

## 3. 壳本体与文档提及（非调用）

| 位置 | 性质 |
|---|---|
| `app/services/agent_service.py:21` | `async def stream_chat(...)` **壳本体**：透传到 `run_chat_pipeline`，并负责 `trace` 兜底创建与 `observability` trace context 的 set/reset |
| `app/services/agent_service.py:3,16` | docstring 与 `__all__`（对外符号声明） |
| `app/application/agent_runtime/inbound.py:5,11` | docstring 提及（RT-013 明示「执行入口接管属 RT-015」） |
| `app/channels/feishu/adapter.py:219` | docstring 提及（RT-013 薄适配说明） |

## 4. 测试耦合点（不计入生产入口，但决定壳的退役时点）

### 4.1 直接调用（17 文件 / 18 处）

| 文件 | 处数 | 行 |
|---|---|---|
| `tests/e2e/test_debug_correlation.py` | 1 | 60 |
| `tests/e2e/test_debug_evaluation.py` | 1 | 51 |
| `tests/e2e/test_debug_llm_calls.py` | 1 | 55 |
| `tests/e2e/test_debug_prompts.py` | 1 | 58 |
| `tests/e2e/test_debug_trace_persist.py` | 1 | 37 |
| `tests/e2e/test_scene_cases.py` | 1 | 60 |
| `tests/e2e/test_trace_collector.py` | 1 | 39 |
| `tests/integration/test_observability_llm_turn_capture.py` | 1 | 43 |
| `tests/integration/test_observability_prompt_snapshots.py` | 1 | 41 |
| `tests/integration/test_observability_turn_decisions.py` | 2 | 54, 76 |
| `tests/integration/test_state_update_flow.py` | 1 | 99 |
| `tests/unit/test_llm_cost_gate.py` | 1 | 36 |
| `tests/unit/test_orchestration_v2.py` | 1 | 26 |
| `tests/v7.8/test_performance.py` | 1 | 45 |
| `tests/v7.8/test_trace.py` | 1 | 44 |
| `tests/v8/test_event_trigger.py` | 1 | 37 |
| `tests/v8/test_world_performance.py` | 1 | 32 |

### 4.2 打桩替换（6 文件 / 15 处）

| 文件 | 处数 |
|---|---|
| `tests/integration/test_feishu_adapter_turn.py` | 7 |
| `tests/integration/test_feishu_cases.py` | 2 |
| `tests/integration/test_feishu_isolation.py` | 1 |
| `tests/e2e/test_feishu_disabled.py` | 1 |
| `tests/unit/test_feishu_adapter_stream.py` | 2 |
| `tests/unit/test_feishu_error_matrix.py` | 2 |

---

## 5. 收编本体尚未落地的技术障碍（供下一次执行者）

| # | 障碍 | 事实依据 | 需要的处置 |
|---|---|---|---|
| 1 | **前台段实现不存在** | `STAGE_RUNNERS` 只覆盖自治 Profile 的非 LLM 段（`loop._plain_stage_names()`），前台 9 个段名（`context_assembly` / `turn_decisions` / `mode_stabilize` / `scene_resolve` / `behavior_resolve` / `action_planning` / `reply_generation` / `record_handoff`，以及共享的 `perception`）无实现 | 新建前台段实现（`AgentLoop(..., registry=…)` 支持按 Run 注入注册表，故**无需**改循环内核即可让前台段与自治段同名共存） |
| 2 | **流式 ↔ 段原语的形态冲突** | `AgentLoop._run_stage` 是 `await coro_factory()` 的请求/响应形态，而 `reply_generation` 必须边生成边 `yield {"kind":"token"}` | 需要队列桥接：段内把 token 事件投递到队列，`run_chat_pipeline` 并发排空并 yield；`turn_meta` 须在首个 token **之前**投递（现序：`action_planning` 段末产出 `turn_meta`） |
| 3 | **循环吞异常与前台外抛语义冲突** | `AgentLoop.run()` 对 critical 段异常只记 `aborted` 状态并 **return**，不外抛；而 `EmptyLLMResponseError` 必须外抛到飞书侧（`adapter` 的 empty_response 兜底）与 API 错误映射 | 段实现需捕获并暂存异常，由 `run_chat_pipeline` 在循环收口后重新抛出（保持对外异常语义逐字段不变） |
| 4 | **`logical_clock` 绑定引入行为面** | 循环 `run()` 会 `logical_clock.bind(self.now)`，而现行 `run_chat_pipeline` **不绑定**逻辑时钟 | 收编时必须逐条对照 `logical_clock` 对前台路径（`scene_service` / `world_engine` / `_idle_seconds_since` 等时间读取）的影响，无法证明等价则按 §4.3 D6 按渠道灰度 |
| 5 | **`loop_runs.session_id` 前台未写入** | `run_chat_pipeline` 调 `open_foreground_run(user_id)` 未传 `session_id`（RT-002 已具备该列） | 收编同批补传 `session_id`，否则前台 Run 无法按会话检索（台账可追溯性缺口） |
| 6 | **顺序体规模** | `run_chat_pipeline` 自 323 行起约 330 行为顺序执行体，跨段中间值约 25 个（`state` / `world_ctx` / `selected_goal` / `mode_decision` / `behavior_ctx` / `style_ctx` / `action_intent` / `reply` …） | 拆为 8 个段实现 + 1 个 Run 内状态载体；22 步本体函数逐段调用、零重写（RT-015 §4.3 D2） |

---

## 6. 壳退役判据（满足后可退役）

1. `chat_pipeline.run_chat_pipeline` 已由 `AgentLoop` 驱动，且段序列只来自 `profiles.py`（`test_single_loop_path` 通过）；
2. `tests/e2e` + `tests/golden` 全绿且与收编前基线逐项一致；
3. §4.1 / §4.2 的测试耦合点已完成迁移或确认为「测试应直连新入口」；
4. 生产 2 处调用点（P1 / P2）改为直连 `run_chat_pipeline`；
5. 退役提交需在验收报告中显式登记（`baseline §9 P2` 技术债结清）。
