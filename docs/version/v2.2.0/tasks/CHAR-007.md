# CHAR-007 · PromptBuilder 集成与 Flag 灰度

## Task Overview

### 为什么需要

CHAR-006 已经能产出完整的 `StyleContract`，但如果没有落地接线，契约就是「空转的数据」：

1. **未进 prompt**：`StyleContract` 还没被翻译成 prompt 里的「风格段」，LLM 看不到这些约束，体验层形同虚设。
2. **未接调用方**：`answer_chain` / `PromptBuilder` 的调用点还没有构造 `style_ctx` 的入口。
3. **无灰度开关**：直接上线会影响全部用户，缺 Flag 就无法渐进、无法回滚。

### 解决什么问题

- 把 `StyleContract` 注入 `PromptBuilder` 的 prompt（新增 `style` 段）。
- 在调用方构造 `style_ctx`，失败降级为「无契约仍可回复」。
- 用 Flag 灰度控制整体开关与各子闸，保证「关闭后与 V2.1.0 逐字节一致」。

## Architecture Position

```text
CHAR-006 assemble_style_contract → StyleContract
        ↓ (调用方构造 style_ctx，失败降级 None)
PromptBuilder.build(..., style_ctx)  ← 本 Task 扩展
        ↓ 新增 style 段
answer_chain → LLM
        ↓
runtime_traces 记录 StyleContract (jsonb)
```

- **上游**：CHAR-006 的 `StyleContract`；`PromptBuilder` / `answer_chain` 既有接缝。
- **下游**：最终 prompt、LLM 生成、trace 审计。
- **边界**：是**落地接线层**，不改变 `answer_chain` 的模型调用本体、不新建 Chat Pipeline。

## Responsibility

**负责：**
- `PromptBuilder.build()` 新增 `style_ctx` 参数与 `build_style_section`（风格段翻译）。
- 在调用方（`answer_chain` / chat pipeline 装配处）构造 `style_ctx`，失败降级 `None`。
- 新增 Flag（总闸 + 子闸），双开才生效，关闭后行为与 V2.1.0 一致。
- StyleContract 随 `runtime_traces` 记录（不建新表，裁决 Q2）。

**不负责：**
- 不做风格契约的**装配与冲突消解**（那是 CHAR-006 的职责）。
- 不改变 `behavior_ctx`（`behavior_ctx` 保留不动，style 段与之并列，裁决 Q5）。
- 不改变 `answer_chain` 的模型调用、流式输出、token 记账本体。
- 不新建数据库表（trace 复用既有）。

## Data Model

### 无新表；新增 settings 字段

| 项 | 类型 | 说明 |
|---|---|---|
| `style_ctx` | `StyleContract \| None`（参数） | `PromptBuilder.build()` 新参数 |
| Flag 常量 | settings 字段 | 总闸 + 子闸（见下） |
| StyleContract | jsonb | 随 `runtime_traces` 记录 |

### Flag 设计（沿用 v2.1 的 domain settings 惯例）

| Flag | 默认 | 控制 |
|---|---|---|
| `v22_experience_enabled` | off | 总闸，关闭即整个 V2.2.0 失效 |
| `v22_emotion_transition_enabled` | off | 情绪表达映射子闸 |
| `v22_relationship_addressing_enabled` | off | 关系表达档子闸 |
| `v22_habit_runtime_enabled` | off | 习惯触发子闸 |
| `v22_style_contract_enabled` | off | StyleContract 装配 + style 段注入子闸 |

> 灰度策略：总闸 + 子闸**双开**才生效；每个子闸独立可回滚。建议开启顺序：`style_contract`（框架先上，风格段可空/降级）→ `emotion_transition` → `relationship_addressing` → `habit_runtime`。

## Core Components

| 组件 | 类型 | 职责 |
|---|---|---|
| `PromptBuilder.build(..., style_ctx=None)` | 方法扩展 | 新增 style_ctx 参数，装配时注入 style 段 |
| `build_style_section(style_ctx) -> str` | 纯函数 | 把 StyleContract 翻译为 prompt 风格段（含 `_literal` 转义 + 字符预算） |
| `_build_style_ctx(state, analysis)` | 调用方纯函数 | 调 CHAR-006 构造 style_ctx，异常降级 None |
| Flag 读取 | settings 方法 | 总闸 + 子闸判定 |

## Runtime Flow

```text
每轮前台 Run（表达切面）：
    ↓
调用方（answer_chain / chat pipeline 装配处）：
    若 v22_experience_enabled 且 v22_style_contract_enabled：
        try: style_ctx = assemble_style_contract(...)
        except: style_ctx = None   ← 降级「无契约仍可回复」
    否则 style_ctx = None
    ↓
PromptBuilder.build(..., style_ctx)：
    若 style_ctx 非空 → 注入 build_style_section(style_ctx) 作为 style 段
    ↓
answer_chain → LLM 生成
    ↓
trace.record 记录 StyleContract(jsonb)
```

## Integration

| 系统 | 集成方式 | 说明 |
|---|---|---|
| **Chat（answer_chain / PromptBuilder）** | **扩展接缝** | 新增 style 段；`answer_chain` 模型调用本体不动 |
| **Memory** | 无 | 不读不改 |
| **Reflection** | 无 | 不产/不读 Insight |
| **Autonomy / Decision** | 正交 | 表达切面；不干预决策（裁决 Q6：独立纯函数，串行调用） |
| **CHAR-006** | 编排调用 | 构造 style_ctx 的唯一上游 |
| **Trace（runtime_traces）** | 复用记录 | StyleContract 以 jsonb 记录，不建新表 |

## Edge Cases

| 场景 | 处理 |
|---|---|
| Flag 关闭 | `style_ctx=None`，PromptBuilder 输出与 V2.1.0 逐字节一致 |
| `assemble_style_contract` 抛异常 | 捕获，`style_ctx=None`，回复链路不中断 |
| style 段字符预算超限 | 沿用既有 `_append_within_budget` 惯例截断，不挤占记忆/历史预算 |
| `style_ctx` 为最小契约（仅硬约束） | 正常注入，风格段仍有效 |
| trace 记录失败 | 不影响回复，仅日志告警 |

## Implementation Plan

1. **Step 1**：在 settings 新增 5 个 Flag（总闸 + 子闸），沿用 `_shared.py` / domain settings 惯例。
2. **Step 2**：`PromptBuilder.build()` 新增 `style_ctx` 参数与 `build_style_section`；在调用方构造 `style_ctx`（调 CHAR-006，失败降级 None）。
3. **Step 3**：接入 trace 记录；编写回归测试（Flag on/off 两条路径 + 降级路径），确认既有 chat 链路测试全绿。

## Acceptance Criteria

- [ ] Flag 关闭时，PromptBuilder 输出与 V2.1.0 逐字节一致（回归断言）。
- [ ] Flag 开启且 style_ctx 非空时，prompt 出现「本轮表达风格」段且含称呼/语气/习惯/禁止项。
- [ ] style_ctx 构造失败时降级为 None，回复链路不中断。
- [ ] 不新建数据库表；StyleContract 记录进 trace。
- [ ] `behavior_ctx` 保留不动，style 段与之并列（不删除、不改语义）。
- [ ] 既有 chat 链路回归测试全绿；新增集成测试覆盖 Flag on/off 两条路径。
- [ ] `pytest` 全绿；`pylint` 评分不低于基线。
