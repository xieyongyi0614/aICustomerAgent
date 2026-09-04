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
