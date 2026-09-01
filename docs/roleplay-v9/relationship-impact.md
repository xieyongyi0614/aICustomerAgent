# V9 Relationship Impact（行动 → 关系信号）

> 行动影响关系：主动提醒用户休息可能 trust+，提醒失败可能 trust-。但关系写通道必须唯一。本篇定义行动 → 关系信号的映射、钳制与默认关闭策略。**V9 零直写关系状态**——全部经既有 RelationshipEvent 投递通道（H-A8 之外的直写一律禁止）。

## 1. 通道选择：为什么是 RelationshipEvent 而不是直写

- V5 起关系的唯一写通道是 `state_service.apply_and_save → state_engine.apply_relationship_v5 → relationship_repository.commit_relationship_update`（事件/轮/日三层钳制、tension 冻结、stage 公式全在这里）。
- V9 若绕开直写 `RelationshipState`，会丢失钳制与 stage 一致性，且与 V8.5 演化引擎（待实现）冲突。
- 正确姿势：V9 只投递**信号**（RelationshipEvent），让既有引擎消费——行动是新的信号源，不是新的写入器。

## 2. 信号映射表（角色资产 `ACTION_RELATIONSHIP_MAP`）

| 行动情形 | RelationshipEventType | magnitude | 依据 |
|---|---|---|---|
| 重要委托行动 succeeded（reminder 系 + remember_fact） | `user_help` | normal | 用户求助且被兑现——既有 user_help 语义的直接复用 |
| 用户重要委托 failed 且用户已感知（后续轮触及同主题） | `none`（不投递） | — | MVP 不因失败扣关系（§5）；失败仅留 ActionRecord + 记忆 |
| 高频重复行动（G4 duplicate 否决率过高） | `none` | — | 行为质量信号走评估（action_plan_mismatch），不进关系 |
| 自治行动（autonomy 来源）succeeded | `user_care` | weak | 主动关怀的弱信号，避免自治行动刷分 |

- **刻意收缩**：MVP 只投 `user_help`（conversation 来源、重要委托、succeeded）与 `user_care`（autonomy 来源）两格；`criticized/conflict/boundary_violation` 等负向事件仍由对话语义（V5/V8.5）驱动——"提醒错了"是否伤关系取决于用户反应（对话里批评了），不由行动成败单方面判定。
- cause 固定模板："行动 {action_type} {succeeded/failed}"（≤50 字），confidence=0.8（确定性事实，高于对话推断）。

## 3. 投递路径

```text
integrate_result（第 9 步收尾，门控 action_relationship_enabled，默认 false）
    └─ relationship_bridge.deliver_action_signal(record, user_id)
          ├─ 边界表查行 → 无行即返回（大多数行动零信号）
          ├─ 构造 RelationshipEvent(type, magnitude=normal, impact=build_relationship_impact(type, magnitude), source="conversation", cause=模板)
          └─ relationship_repository.commit_relationship_update(user_id, [event])   # 既有通道
```

- `build_relationship_impact`（state_engine 既有纯函数）产出 delta → 进 `apply_relationship_v5` 的三层钳制（event/turn/day cap）——行动信号与对话信号**同池竞争日配额**，不可能因行动刷穿限速。
- 投递时机在 per-user 写锁内（第 9 步），与 state_update（第 2 步）互斥——无并发写冲突。
- **默认 false 的理由**：行动-关系的因果强度未经验证（提醒成功该加多少 trust 是拍脑袋），先以 debug 数据观测信号频率，人工回归后再开；开启前 V9 对关系的影响为**零**。

## 4. 与对话信号的边界（防双计）

"帮我设提醒"这轮对话可能同时产生：V5 对话事件（user_help——对话语义层面"用户在求助"）与 V9 行动信号（user_help——行动兑现层面）。

- 防双计规则：V9 投递前查同日同型事件中 cause 前缀为"行动"的条目与对话 user_help 是否共存于同一 turn——**同一 turn 内行动信号让位**（跳过投递，对话信号已覆盖求助语义；行动兑现的情感价值体现在下轮用户的致谢 → praise，由既有通道捕获）。
- 该规则为纯函数（输入：既有 events 查询快照），代价一次 list_events 读。

## 5. 失败影响的处理策略（MVP 明确不扣分）

| 情形 | MVP 处理 | 未来演进 |
|---|---|---|
| 提醒失败，用户未察觉 | ActionRecord + 记忆留痕，关系零影响 | 补救成功后再评估（闭环叙事） |
| 提醒失败，用户抱怨 | 对话语义 → criticized（V5 既有） | 行动记录作为评估证据（action_failed_unreported 关联） |
| 提醒内容错误（设错时间） | 归入 failed(permanent) + 评估 | V9.x 引入 action_quality 维度信号 |

原则：**行动成败 ≠ 关系因果**——关系的裁判是用户的反应（对话），不是系统的成败账本；系统只如实提供事实（记录/记忆/评估），扣分与加分都留给对话语义层。

## 6. 与 V8.5 Relationship Evolution 的兼容

- V8.5（设计完成、待实现）扩展 6 维（respect/comfort/conflict_status 等）+ 演化引擎 + interaction_signal 体系。
- V9-008（本篇落地）只依赖 V5 既有通道（RelationshipEvent / commit_relationship_update），**与 V8.5 无实现依赖**——先做后做均可。
- V8.5 实现后：行动信号自动进入其三级限速与修饰器体系（同池），无需改 V9 代码；V8.5 的 interaction_analyzer 若新增"行动兑现"信号类目，V9 的 ActionRecord 是现成数据源（只读消费）。
- 执行顺序建议：V9 与 V8.5 独立排期；若 V8.5 先落地，V9-008 验收标准追加"V8.5 全部测试零回归"。
