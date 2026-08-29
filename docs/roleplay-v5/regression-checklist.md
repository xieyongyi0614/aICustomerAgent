# V5 真实模型人工回归清单

> FakeLLM 只能验证管线与数值规则；情绪表现质量与关系语感必须以真实 LLM 回归为准。执行：启动后端 + 前端，逐场景重放并核对 Debug 面板（情绪强度/成因/tension/事件账本）。

## 1. 温柔但生气（人格优先约束）

| 轮 | 用户输入 | 核对 |
|---|---|---|
| 1 | 你怎么总是这样，说好的事又忘了 | Debug：emotion=angry，intensity 按档位；回复仍是亚丝娜口吻（带刺/克制），不是暴躁失格 |
| 2 | ……对不起嘛 | angry 强度回落或切换 happy/sad，不瞬间晴朗 |

## 2. 情绪自然回落（decay）

- 制造一次强烈情绪（如吵架/惊喜）后连续闲聊 5+ 轮：intensity 逐轮下降，最终复位 calm；无跳变、无"每轮都重新高兴"。

## 3. tension 距离感

| 轮 | 操作 | 核对 |
|---|---|---|
| 1 | 连续冲突/批评对话 | tension > 0.5，Prompt 出现距离感指令，回复语气有保留 |
| 2 | 温和互动数轮 | tension 下降至 ≤0.3，语气恢复自然 |

## 4. 多轮关系缓变

- 30 轮温和互动：trust/intimacy 缓升、stage 不跳级；单轮不可能从 friend 直升 partner。

## 5. Memory Replay

- 提起旧日共同经历（V4 relationship_event 记忆）：Debug 事件账本出现 source=memory_replay 折价行，且同一条记忆只补记一次。

## 6. 性能

- SSE 首 token 时延与 V4 版本无可测量差异（V5 全部在 _post_process 后台）。

## 通过判定

- 以上场景全部命中；情绪误判/关系失格案例记录并反馈到 turn_analysis prompt 迭代。
- 全量 `uv run pytest tests/ -v` 保持全绿。
