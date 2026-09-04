# Phase 4 Regression Checklist — Long-term Relationship

## Golden 行为（绝对不许变化）

1. **V8.5 数值引擎字节级**：evolve() 对相同输入（信号/状态/flags）输出与 v1 完全一致（replay 工具验证）。
2. 限速、迟滞、12 项数值里程碑判定逻辑不变。
3. Flag OFF：关系行为与 v1 一致（无 shared experience 段、无 Pattern 注入、不转写）。
4. P1/P2/P3 全部 golden 不回退。

## 必须重跑的旧版本回归

| 来源 | 范围 | 触发条件 |
|---|---|---|
| V8.5 regression-checklist（v1.0.0/v8.5/） | 数值引擎全量 | **每 Task 合入（硬门）** |
| V8 World checklist | 投影读 world_events 不改写 | REL-002 |
| P1~P3 Eval Gate | 上游不回退 | 每灰度推进 |

## 执行步骤

```text
1. evolve() 重放字节级对比（replay 工具）
2. V8.5 checklist 全量
3. Flag OFF golden + 投影对账
4. 结果记录附录
```
