# Phase 5 Regression Checklist — Life Loop

## Golden 行为（绝对不许变化）

1. Flag OFF：v1 autonomy tick（60s + 内存 registry + 5 循环）行为不变。
2. Action/World 引擎函数零改动（输入输出断言测试）；AutonomyPolicy 纯函数本体不变。
3. 前台路径永不熔断；用户消息处理延迟无回归。
4. P1~P4 全部 golden 不回退。

## 必须重跑的旧版本回归

| 来源 | 范围 | 触发条件 |
|---|---|---|
| V7 autonomy regression-checklist（v1.0.0/v7/） | 触发/预算/主动消息全项 | **每 Task 合入（硬门）** |
| V9 action checklist | outbox 改造不破坏 action 语义 | LIFE-004 |
| V8 World checklist | outbox 消费复用引擎 | LIFE-004 |
| P1~P4 Eval Gate | 上游不回退 | 每灰度推进 |

## 执行步骤

```text
1. Flag OFF：V7 checklist + 引擎断言
2. Flag ON：kill -9 演练 + 7 天空跑 + 幂等重放
3. 引擎函数输入输出快照对比
4. 结果记录附录
```
