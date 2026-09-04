# Conversation Mode

## 1. 问题与决策

### 1.1 现状

RoleMode（professional / default / immersive）每轮由 router_chain 即时推断，不落任何持久层：
`conversations` 表仅 id/user_id/created_at/updated_at 四列。低置信轮次或用户话题跳变（技术→日常→情感）时，mode 逐轮跳变 → `MODE_INSTRUCTIONS` 段每轮漂移 → 人格表现不稳定（问题 5）。

### 1.2 关键边界决策：不引入第二套模式枚举

题设列举的 daily / playful / comfort / serious / romantic 属「对话基调」，与 RoleMode（表达强度与优先级）是两个维度。决策：

- **Mode 管「强度与优先级」**：professional / default / immersive（V1 枚举不变）。
- **基调管「这一轮怎么表现」**：由 Behavior Strategy 承担——comfort 基调 = quiet_companion/direct_support 的稳定出现；romantic 基调 = affectionate_expression 按 stage 预算放开。基调是**轮次策略序列的宏观表现**，不需要独立持久化状态。

如果同时持久化「Mode + 基调」两套维度，prompt 将出现两个互相竞争的「当前氛围」声明，恰恰制造要消除的漂移。V6.5 的答案：一个 Mode（持久化），一个 Strategy（每轮解析），正交不重叠。

## 2. 数据模型与持久化

```python
# conversations 表新增两列（迁移 0010）
mode: str = "default"               # professional | default | immersive，CheckConstraint 三值
mode_entered_at: datetime | null    # 当前 mode 进入时间（空闲回落计算用）
```

- 存会话级而非 user 级：一个用户多个会话可以有不同 mode；conversations 表是会话的唯一归属表，加列即可，不建新表。
- Mode 持久化值 ≠ 本轮生效值（见稳定器）：DB 存「已确认模式」，本轮 prompt 用「生效模式」。

## 3. 生命周期

### 3.1 创建

`conversation_service.ensure_conversation` 建行时 mode=default, mode_entered_at=now。首轮无迁移负担（列有默认值）。

### 3.2 更新：迟滞稳定器（核心）

router 每轮照常输出候选 mode（LLM 行为不变），稳定器决定「生效值」与「是否写回」：

```python
# app/services/mode_service.py（新增）
def stabilize(
    confirmed_mode: str,        # DB 确认值
    candidate: str,             # router 本轮候选（含低置信降级后的 effective_mode）
    confidence: float,          # router 原始置信度
    turns_in_candidate: int,    # 会话内连续同候选轮数（内存 dict 记账，key=session_id）
    idle_seconds: float,        # mode_entered_at 距今
) -> ModeDecision
```

规则（表驱动，全部纯函数）：

| 规则 | 条件 | 结果 |
|---|---|---|
| R1 无感 | candidate == confirmed_mode | 生效=confirmed，计数清零 |
| R2 迟滞 | candidate ≠ confirmed 且 confidence ≥ 0.7 且连续轮数 ≥ 2 | 生效=candidate，**写回 DB**，计数清零 |
| R3 观望 | candidate ≠ confirmed 但不满足 R2 | 生效=confirmed（沿用旧模式），候选计数 +1，不写回 |
| R4 空闲回落 | idle_seconds > 2h（可配置 mode_idle_reset_seconds） | 生效=default，写回 DB |
| R5 失败兜底 | router 链失败/非法 | 生效=confirmed（不是 default！模式不因一次故障跳变） |

- **每轮变化的三个来源全部被堵住**：低置信（R3 观望 + 现有 confidence 门槛）、话题单轮跳变（R2 需连续 2 轮 + 高置信）、服务故障（R5 保持确认值）。
- `turns_in_candidate` 计账在 chat_pipeline 内存 dict（进程级，key=session_id）；重启归零只是多轮观望，无正确性影响。不为此建表。
- 连续轮数阈值与置信阈值进 settings（`mode_switch_min_confidence=0.7`、`mode_switch_min_turns=2`、`mode_idle_reset_seconds=7200`）。

### 3.3 过期与回落

- 长时间不互动（> 2h）后第一条消息回落 default（R4）——模式是会话氛围，冷启动回归日常；immersive 需要用户重新自然进入。这是「过期策略」的收口：不做定时器，不加后台任务，**读时判定**。
- 显式切换：用户明确说「进入沉浸模式」类诉求由 router 高置信捕获 → 连续 2 轮要求即切换（迟滞不变，防止单轮误切）。用户体验代价是多一轮确认，换取的稳定性值得。

## 4. 编排接入

```text
context_builder.build
  └─ 读 conversations.mode / mode_entered_at（现有会话行顺带，零额外查询——ensure_conversation 已在）

gather（router 照常出候选，LLM 不变）
gather 后：
  mode_service.stabilize(...)          # 纯函数，微秒级
  → effective_mode（本轮 prompt 用，替代现有 _effective_role_mode 的输出位）
  → pending_mode_write（或 None）

answer_chain.astream(effective_mode.mode, ...)   # 现有签名不变

conversation_service.save_turn(...)
  └─ pending_mode_write 非空时同事务 UPDATE conversations.mode
```

- 写回随 save_turn 同事务：无新后台步骤、无独立 UPDATE 往返、崩溃时模式与消息同生共死。
- `_effective_role_mode` 现有逻辑（低置信降级 default）调整为产出「候选 + 置信度」，裁决交给 stabilize——保留其日志与 trace 语义。

## 5. Mode 与其他层的关系

| 层 | 关系 |
|---|---|
| Behavior Strategy | mode=professional 是 Strategy 最高优先修饰（规则 1）；mode 决定 Budget 基线 |
| ActionBudget | professional → 0 动作；default/immersive 基线 1/2（action-budget.md §4） |
| V3 rhythm | 互不影响（V3 response-rhythm.md §6 既有结论：mode 只影响语言风格） |
| V5 emotion / V6 goal | 不读写 mode；mode 是会话氛围层，不是内在状态 |

## 6. 测试要点

- 稳定器矩阵：R1~R5 全覆盖（unit）；会话序列「default→immersive 单轮跳变不生效、连续 2 轮才切换」（integration）。
- 持久化：迁移 0010 与 ORM 一致、默认值回填、save_turn 同事务写回（integration）。
- 行为回归：现有 router 降级测试改造后语义不变（故障时生效=confirmed 而非 default，需更新断言）。
