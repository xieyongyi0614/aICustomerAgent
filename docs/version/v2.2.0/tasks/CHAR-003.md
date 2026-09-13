# CHAR-003 · Personality Profile 结构化与轴调制

## Task Overview

### 为什么需要

人格目前以**静态 Prompt 文本**存在（`identity.py` 的「核心人格」、`personality.py` 的「语言风格」）。这种形态有两个问题：

1. **不可结构化消费**：人格是一段自由文本，无法被程序识别「哪些是核心人格、哪些是禁止项、哪些是语言风格」，也就无法在 StyleContract 里把「硬约束」和「可调制风格」分开处理。
2. **轴不可调制**：V2.1.0 已经设计了 `personality_state`（有界人格轴：assertiveness/warmth/curiosity/patience），但该状态只设计给 Evolution Engine 读，**尚未反向作用于表达生成**——人格演化对「说话方式」没有实际影响。

### 解决什么问题

- 把人格从「一段 Prompt」升级为**结构化 `PersonalityProfile`**（核心人格/行为偏好/语言风格/禁止项/原则五类），让硬约束与可调制风格显式分离。
- 实现 `personality_state` 轴 → `PersonalityModulation` 的**读侧调制**，让人格演化真正影响表达。

## Architecture Position

```text
identity.py / personality.py (静态资产，原样保留)
        ↓ 语义等价迁移（不删不改）
PersonalityProfile (结构化投影，本 Task 新增)
        ↓
personality_state (V2.1.0 演化轴，可选读)
        ↓ 读侧叠加，bound 钳制
build_personality_modulation → PersonalityModulation
        ↓
StyleContract.personality_modulation + forbidden + principles
        ↓
CHAR-006 装配 → CHAR-007 prompt 注入
```

- **上游**：Persona 静态资产（`identity.py` / `personality.py`）+ V2.1.0 `personality_state`（可选）。
- **下游**：`PersonalityModulation` + `forbidden` / `principles` 填入 `StyleContract`。
- **边界**：人格是**配置期资产 + 慢变量演化**的混合，本 Task 只做「读 + 翻译」，**永不写回**。

## Responsibility

**负责：**
- 定义结构化 `PersonalityProfile`（五类字段），从既有文本**语义等价迁移**。
- 实现 `build_personality_modulation(profile, personality_state=None)`：无演化轴返回基线，有演化轴在 `bound` 内叠加。
- 输出 `forbidden` / `principles` 硬约束（不可被调制稀释）。

**不负责：**
- **不修改、不删除** `identity.py` / `personality.py`（Persona 不可写回铁律）。
- 不写 `personality_state`（演化写回走 V2.1.0 Evolution Engine，本 Task 只读）。
- 不读 Memory 原始事实（人格不经 Memory 调制，沿「Development ← Reflection 单向」约束）。
- 不实现人格的**演化逻辑**（那是 V2.1.0 的职责，本 Task 只消费演化结果）。

## Data Model

### 结构化资产 + 纯函数，零新表

| 项 | 类型 | 说明 |
|---|---|---|
| `PersonalityProfile` | 配置资产（`character/asuna/personality_profile.py`） | 五类字段，Persona 声明 |
| `PersonalityModulation` | 值对象（CHAR-001 定义） | 产出物，不落表 |
| `personality_state` | 只读（V2.1.0 表） | 有界人格轴，可选 |

### `PersonalityProfile` 字段（五类）

| 字段 | 类型 | 来源 | 示例 |
|---|---|---|---|
| `core_traits` | `list[str]` | `identity.py` 核心人格 | 温柔但坚定 / 独立自主 / 认真负责 |
| `behavior_preferences` | `list[str]` | `identity.py` + `habits` 语义 | 先行动后开口 / 先倾听后建议 |
| `language_style` | `str` | `personality.py` 语言风格 | 简短口语化、1~3 句、避免客服腔/梗/颜文字 |
| `forbidden_behaviors` | `list[str]` | `identity.py` | 不无条件赞同 / 不越界 / 不表演 |
| `principles` | `list[str]` | `identity.py` | 有自己的判断 / 冷静果断 / 守护亲近的人 |

### 人格轴（默认基线 + bound，实现期与角色设定对齐）

| 轴 | baseline | bound | 语义 |
|---|---|---|---|
| `assertiveness` | 0.3 | ±0.3 | 主动程度、建议确定性 |
| `warmth` | 0.8 | ±0.2 | 关心显性程度、亲昵度 |
| `curiosity` | 0.6 | ±0.2 | 提问倾向、追问深度 |
| `patience` | 0.7 | ±0.2 | 倾听与给建议的先后 |

## Core Components

| 组件 | 类型 | 职责 |
|---|---|---|
| `PersonalityProfile` | 配置资产 | 五类字段的静态声明 |
| `build_personality_modulation(profile, personality_state=None)` | 纯函数 | 基线导出默认轴；有演化轴时在 bound 内叠加；输出 forbidden/principles |

## Runtime Flow

```text
每轮 Run：
    ↓
读取 PersonalityProfile（静态，每 Run 一次）
    ↓
若 v21_personality_evolution_enabled 且 personality_state 存在：
    读各轴 current，在 bound 内叠加到 baseline
否则：
    直接用 baseline 常量
    ↓
产出 PersonalityModulation（四轴 + baseline/bound 元数据）
    ↓
forbidden / principles 直接取自 Profile（硬约束，不经调制）
    ↓
填入 StyleContract
    ↓
CHAR-006 装配 → CHAR-007 注入 prompt
```

## Integration

| 系统 | 集成方式 | 说明 |
|---|---|---|
| **Chat** | 无直接集成 | 经 CHAR-006/007 进入 prompt |
| **Memory** | 无 | 人格不经 Memory 调制 |
| **Reflection** | 无（间接） | 演化只经 Reflection→Evolution 通道，本 Task 不直接读 Insight |
| **Autonomy / Decision** | 无 | 表达切面正交 |
| **Evolution（V2.1.0）** | **只读消费** | 读 `personality_state` 轴结果，写回走 Evolution Engine |
| **Character / Persona** | **读侧投影** | 新增 `personality_profile.py`，原 `identity.py`/`personality.py` 原样保留 |

## Edge Cases

| 场景 | 处理 |
|---|---|
| `personality_state` 不存在 / Flag 关闭 | 返回 baseline 默认轴，不报错 |
| 轴 `current` 越界（超出 `baseline ± bound`） | `bound` 钳制，取边界值 |
| `forbidden` / `principles` 为空 | 配置期校验失败（Profile 定义时保证非空）；运行时防御兜底为默认硬约束 |
| 轴叠加导致四轴全为 0 | 合法但极端状态，不影响 forbidden/principles；由评估回归观察 |
| 演化轴缺某轴（部分轴未演化） | 缺失轴回退 baseline，不整体失败 |

## Implementation Plan

1. **Step 1**：新建 `app/character/asuna/personality_profile.py`，从 `identity.py` / `personality.py` 语义等价迁移五类字段，并定义四轴 baseline/bound。
2. **Step 2**：新建 `app/services/experience/personality_modulation.py`，实现 `build_personality_modulation`（baseline 导出 + bound 钳制叠加 + 硬约束透传）。
3. **Step 3**：编写单测（默认调制、轴叠加、bound 钳制、硬约束恒在、缺轴回退），并写对照表验证 Profile 与原文语义一致。

## Acceptance Criteria

- [ ] `PersonalityProfile` 五类字段齐全，与 `identity.py`/`personality.py` 语义一致（有对照验证）。
- [ ] 无演化轴返回确定性默认调制；有轴叠加被 `bound` 钳制。
- [ ] `forbidden` / `principles` 在任何情况下非空且不被轴调制稀释。
- [ ] 不修改、不删除既有 `identity.py` / `personality.py`。
- [ ] 缺轴回退 baseline，不整体失败。
- [ ] 单测覆盖：默认调制、轴叠加、bound 钳制、硬约束恒在、缺轴回退。
- [ ] `pytest` 全绿；`pylint` 评分不低于基线。
