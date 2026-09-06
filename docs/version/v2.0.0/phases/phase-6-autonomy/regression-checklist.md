# Phase 6 Regression Checklist — Advanced Autonomy

## Golden 行为（绝对不许变化）

1. Flag OFF：v1 扁平 4 类 goal 行为逐字节一致（层级字段空 = 走 v1 路径）。
2. Goal 不写 Scene/Memory/World（依赖矩阵断言）。
3. 既有 conversation/scene goal 的选择与生命周期语义不变。
4. P1~P5 全部 golden 不回退。

## 必须重跑的旧版本回归

| 来源 | 范围 | 触发条件 |
|---|---|---|
| V6 goal checklist（v1.0.0/v6/） | 既有 goal 语义 | **每 Task 合入（硬门）** |
| V7 autonomy checklist | Planning 不破坏触发/预算 | AUT-002~003 |
| P1~P5 Eval Gate | 上游不回退 | 每灰度推进 |
| v2.0.0 全量 Flag ON/OFF 双态对比 | 全链最终验收 | v2 全量前 |

## 执行步骤

```text
1. 旧 goal 行为快照对比（Flag OFF）
2. V6/V7 checklist
3. 跨会话剧情集（ON/OFF 双态）
4. 全量验收 → v2.0.0 全量发布评审
5. 结果记录附录
```

## 结果记录附录（AUT-005 回写，2026-09-09）

### 离线部分（已执行，确定性 stub）

| 项 | 结果 |
|---|---|
| 步骤 1 Flag OFF 旧 goal 行为快照 | tests/v2 全量 Flag OFF 用例绿（v1 review/select/到期路径逐字节；goal_supply/goal_advance 步骤 skipped 记账） |
| 步骤 2 V6/V7 checklist 对应单测/集成面 | goal/autonomy/action 单测与矩阵回归绿 |
| 步骤 3 跨会话剧情集（ON 态） | tests/eval/test_autonomy_eval_gate.py 4 例全过：完成分支（跨 3 会话）/失败分支（阈值→重规划→耗尽→failed）/放弃分支（双信号置信）/冲突+复活+第 4 次规划拒绝 |
| E-AUT-01~04 Gate | 全过（规划产物 100% 过闸、封顶断言、推进/失败语义、一致性规则零违例、剧情通过） |
| 全量回归 | 见 tasks.md 实现状态回写（阶段收口数字） |

### 待人工执行（真实模型）

- V6 goal checklist / V7 autonomy checklist 真实模型重跑（E-AUT 规划质量 Judge 真实采样）
- 规划质量 Judge 真实 LLM 采样评审（离线为固定桩）
- Flag ON/OFF 双态真实对话对比与灰度推进（`v2_autonomy_advanced_enabled` 申请材料已齐备）
- 前置灰度项：`v2_life_loop_enabled`、`action_enabled`（Sub-Goal 执行依赖 v9 总闸）需先于/同步开启
