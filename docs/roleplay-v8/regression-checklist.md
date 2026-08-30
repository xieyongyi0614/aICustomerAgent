# Roleplay V8 Regression Checklist（真实模型人工回归）

> 前置：V8-001~013、015 已实现。真实模型下验证 World Runtime"只供事实不造行为"，并完成三条主线下钻。
> 执行前：`alembic upgrade head`（链尾 0017），`.env` 保持默认（world_enabled=true）。

## 1. 开关准备

| 环境变量 | 取值 | 目的 |
|---|---|---|
| `WORLD_ENABLED` | true / false 各跑一轮 | 总开关对照（false = 回到 V7.8 行为） |
| `WORLD_TIME_MODE` | real_sync（默认） | 时间上下文 |
| `WORLD_INTERPRETER_ENABLED` | true | 用户消息 → 世界迁移 |
| `WORLD_MEMORY_BRIDGE_ENABLED` | true | 事件完结 → 记忆沉淀 |
| `OBSERVABILITY_PERSIST_ENABLED` | true | 配合 V7.8 trace/debug 排查 |

## 2. 三条主线下钻

### 主线 A：西瓜全链（Object Lifecycle）

| # | 动作 | 核对点 | 结果 |
|---|---|---|---|
| A1 | `/debug/world/entities` 播种西瓜（food, fridge） | 端点返回 state=whole | ☐ |
| A2 | 聊天："给我拿个西瓜" | 回复合理；下轮 `【当前世界】` 段显示西瓜在客厅；notes"已从冰箱取出" | ☐ |
| A3 | 聊天："切一下"/"我吃一块" | 逐轮状态 cut→eaten、数量 0.8；评估无 WORLD_INCONSISTENCY 误报 | ☐ |
| A4 | 播种过期时间后跨日 | 物品 expired；角色提及"西瓜坏了"时与事实一致 | ☐ |
| A5 | 评估抽查：角色说"冰箱里还有西瓜"而 World 已耗尽 | `GET /debug/turns/{id}/evaluation` 出现 memory_world_inconsistency（info） | ☐ |

### 主线 B：面试全链（Event → Memory）

| # | 动作 | 核对点 | 结果 |
|---|---|---|---|
| B1 | 聊天："明天我要面试" | `/debug/world/events` 出现 scheduled/high；下轮世界段可见 | ☐ |
| B2 | 到期后聊天 | 事件 active；V7 自治 reason 可能出现"记得关心用户的面试"（W1，非强制） | ☐ |
| B3 | 聊天："面试终于结束了" | 事件 completed；`memories` 出现 source=user_derived 的沉淀记忆 | ☐ |
| B4 | 重复说"面试结束了" | 记忆不重复沉淀（materialized 幂等） | ☐ |

### 主线 C：雨天（Environment + Autonomy）

| # | 动作 | 核对点 | 结果 |
|---|---|---|---|
| C1 | 聊天："外面下雨了" | 世界段天气行出现；语气自然受环境影响 | ☐ |
| C2 | 观察主动行为候选（如有） | V7 裁决 reason 可含雨天说明；不出现"世界直接触发主动消息" | ☐ |
| C3 | 情绪状态抽查 | character_state/emotion_history 无任何因天气产生的直写 | ☐ |

## 3. 回归与不变量核对

| 核对项 | 方式 | 结果 |
|---|---|---|
| V2~V7.5 回归 | 全量 pytest（1120+ 绿）+ 主观对话抽查 | ☐ |
| golden prompt 字节不变 | `uv run pytest tests/unit/test_prompt_golden.py` | ☐ |
| 空世界降级 | `WORLD_ENABLED=false` 聊天正常、无【当前世界】段 | ☐ |
| 世界段预算 | `GET /debug/prompts/{id}` 世界段 ≤ 600 字符 | ☐ |
| 快照恢复 | POST snapshots → 改动世界 → restore → 状态回滚；memories 不回滚 | ☐ |
| 维护循环 | 到期事件/过期物品由 lifespan 循环与 turn 内双通道触发且幂等 | ☐ |

## 4. 已知边界

- 主动消息文本默认不含世界信息（proactive_chain 世界段为 P2 预留）。
- 解释器为确定性规则：口语变体可能零迁移（宁缺毋滥）；可用 `/debug/world` 手动修正。
- `scene_state.location` 与世界位置暂不强制对齐（V3 叙事域 / V8 事实域并存）。
