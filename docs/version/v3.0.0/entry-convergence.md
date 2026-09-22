# 入口收敛登记（RT-015 产物）

> **上游**：`docs/version/v3.0.0/tasks/RT-015.md` §5 步骤 5、§8 AC6
> **状态**：RT-015 **收编本体已落地**（`chat_pipeline` 改由 `AgentLoop` 驱动，段序列来自 `foreground_chat` Profile）
> **登记口径**：`agent_service.stream_chat` 的全部耦合点按「生产 / 壳本体 / 文档提及 / 测试」四类逐条登记，未登记项由 `tests/v30/test_runtime_foreground_cutover.py::test_agent_service_call_sites_registered` 守门

---

## 1. 结论（收编后）

| 项 | 结论 |
|---|---|
| 壳是否退役 | **保留**。本轮不退役 `app/services/agent_service.py` 的 `stream_chat` 符号 |
| 保留理由 | ① 17 个测试文件直接调用该符号、6 个文件以 `monkeypatch.setattr(agent_service, "stream_chat", …)` 打桩，**测试耦合面 33 处**，退役需单独批次重写测试夹具；② RT-015 §3.2 明确「不删除 `agent_service`（除非调用点全部迁移完毕且登记完成）」 |
| 是否存在未登记双入口 | 否。生产侧仅 2 处调用，且都指向同一条 `run_chat_pipeline` → `AgentLoop` 链路（壳是唯一实现，无平行编排） |
| 收编本体 | **已落地**。`run_chat_pipeline` 内部由 `AgentLoop` + `foreground_chat` Profile 驱动；段序列只来自 `profiles.py`（`test_single_loop_path`） |

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

## 6. 壳退役判据（满足后可退役）

1. `chat_pipeline.run_chat_pipeline` 已由 `AgentLoop` 驱动，且段序列只来自 `profiles.py`（`test_single_loop_path` 通过）；
2. `tests/e2e` + `tests/golden` 全绿且与收编前基线逐项一致；
3. §4.1 / §4.2 的测试耦合点已完成迁移或确认为「测试应直连新入口」；
4. 生产 2 处调用点（P1 / P2）改为直连 `run_chat_pipeline`；
5. 退役提交需在验收报告中显式登记（`baseline §9 P2` 技术债结清）。
