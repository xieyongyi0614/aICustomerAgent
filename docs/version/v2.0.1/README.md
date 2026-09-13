# v2.0.1 — Autonomy Proactive Delivery Patch

> 状态：**Architecture Design（补丁，仅设计未实现）**
> 前置：`docs/version/v2.0.0/` 已设计完成（phase-1~6，AUT-001~005 已实现）
> 定位：**对 v2.0.0 的增量补丁**，聚焦 v2.0.0 phase-5（Life Loop）/ phase-6（Advanced Autonomy）**未覆盖的遗漏点**——「主动消息真实投递链路」。

---

## 1. 为什么是 v2.0.1 补丁，而不是 v2.0.0 内新增

v2.0.0 的 Autonomy 相关能力分两处落地：

| v2.0.0 位置 | 主题 | 现状 |
|---|---|---|
| phase-5-life-loop | 统一生命周期调度（Life Loop Controller + Trigger Registry + 预算/冷却/Idle） | 已设计，LIFE-001~006 已实现 |
| phase-6-autonomy | 角色追求目标（Goal 层级 + Planning + 观察调整 + 冲突仲裁） | 已设计，AUT-001~005 已实现 |

但两者之间有一个**共同的遗漏**：v2.0.0 把「何时触发、何时决策、何时生成」都设计并实现了，却**没有闭环「主动消息真正发到 Channel（Feishu）」这条投递链路**。具体表现为：

- `proactive_executor.execute` 生成文本后只调用 `conversation_service.save_proactive_turn` 落库并置 `delivered`，**从未调用 `delivery.send_proactive`**。
- `delivery.send_proactive`（FEISHU-005 已交付能力）**当前无任何生产调用方**（仅测试调用）。
- `proactive_actions.message_id` 存的是**内部 message row id**，与 Feishu 的 `external_message_id` 语义混用。

这是一个**独立、可增量交付、不破坏 v2.0.0 既有设计**的补丁点，因此作为 **v2.0.1** 单独组织，而不是回插进 v2.0.0 的 phase 里。

---

## 2. 补丁范围

| # | 补丁目标 | 对应 Gap | 优先级 |
|---|---|---|---|
| P1 | 闭合主动消息投递链路（Decision → 生成 → 落库 → **Feishu 真实发送**） | G1 | 最高 |
| P2 | 区分 `internal_message_id` / `external_message_id` | G2 | 随 P1 |
| P3 | 生成与发送两阶段拆分，明确 `delivered` 语义 | G3 | 随 P1 |
| P4 | 调度收敛（`autonomy_worker` 与 `life_loop` 双 tick 源去重） | G4 | 次要 |
| P5 | P0/P1 High Priority Override 通道 | G8 | 次要 |

> 其余 Gap（G5 多候选软排序、G6 偏好→重复提醒、G7 事件触发扩展）**不在本补丁范围**，仍属未来版本，不在 v2.0.1 内实现。

---

## 3. 文档地图

```text
docs/version/v2.0.1/
├── README.md              ← 本文件（补丁定位 + 范围 + Gap 摘要）
├── architecture.md        ← Autonomy 2.0 完整架构（五层心智模型 + 投递链路 + Gap 分析）
└── patch-tasks.md         ← 补丁任务建议（PATCH-AUT-01 ~ 05，非 Task Detail）
```

---

## 4. 与 v2.0.0 的边界

- **不改** v2.0.0 任何 phase 文档、任何已实现的 AUT/LIFE 任务。
- **复用** v2.0.0 已落地的 `trigger_registry` / `proactive_actions` / `background_jobs` / `life_loop` / `ChannelAdapter`。
- **唯一结构改动**（补丁落地时）：`proactive_actions` 增一列 `external_message_id`，不新增表、不建新队列。
- 补丁任务沿用 Autonomy 域前缀，续 AUT 编号为 `PATCH-AUT`，语义上归属「v2.0.0 phase-6 Autonomy 的投递侧收尾」。
