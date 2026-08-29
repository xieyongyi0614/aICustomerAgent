# V7 真实模型人工回归清单

> FakeLLM 只能验证 Autonomy 机制（触发/裁决/队列/重试/并发）；主动消息的自然度、打扰度与人格一致性必须以真实 LLM 回归为准。
> 执行：真实模型环境启动后端（`AUTONOMY_ENABLED=true`，可用 `.env` 覆盖 `AUTONOMY_INACTIVITY_MINUTES=1` 等缩短等待），配合 `GET /api/v1/proactive/pending` 轮询观察。与 V4/V5/V6.5 清单并列执行。

## 0. 开关对照（回归护栏）

| 步骤 | 操作 | 核对 |
|---|---|---|
| 1 | `AUTONOMY_ENABLED=false` 启动 | 日志出现"Worker 未启动"；任意时长闲置零主动消息；聊天行为与 V6.5 完全一致 |
| 2 | `AUTONOMY_ENABLED=true` 启动 | lifespan 日志无 worker 报错 |

## 1. S1 用户离开 → 主动关心（核心场景）

| 轮 | 操作 | 核对 |
|---|---|---|
| 1 | 用户说"我去忙了"后停止互动 | 闲置阈值后 pending 出现 1 条主动消息，intention=check_in |
| 2 | 核对文本 | 一句话、口语化、亚丝娜口吻；**无动作描写**、无追问施压、允许不回复的姿态（"忙完了吗？记得喝口水"类） |
| 3 | 语境衔接 | 主动消息与最后对话内容衔接（不凭空问候）；goal/reason 可在 trace `autonomy_policy` step 查到 |

## 2. S2 睡觉 → 不打扰

- 23:00~08:00 期间制造闲置 → pending 恒空，trace `autonomy_policy` decision=ignore reason="静音时段"。
- 08:00 后闲置 → 正常触发（错过的关心由下一轮闲置自然补上，无"补发"）。

## 3. S3 连续主动防护

| 轮 | 操作 | 核对 |
|---|---|---|
| 1 | 第一次主动后**不回复**，等待 | 第二次主动间隔 ≥ min_interval（亲密度 ≥0.55 时减半但不低于 60 分钟硬底线） |
| 2 | 继续不回应至 episode 上限 | 第 3 次不再主动（attempt=2=max，ignore"本集期已达上限"）；指数退避生效（间隔 ×2） |
| 3 | 用户回复任意消息 | episode 重置；未 ack 气泡自动 acked；candidate 未生成的直接 discarded |

## 4. S4 Memory Trigger（scheduled_followup）

| 轮 | 操作 | 核对 |
|---|---|---|
| 1 | 用户说"我明天有面试，好紧张" | V4 记忆入库（important_event）；日志出现 scheduled_followup 登记（due=次日 18:00） |
| 2 | （时间注入或等到期）| 主动消息为面试近况跟进（check_in），语境自然 |
| 3 | 深夜到期情形 | 静音不豁免：IGNORE"静音时段" |

## 5. S5 与 Chat Flow 冲突

| 场景 | 核对 |
|---|---|
| 主动消息生成期间用户发消息 | 消息无重复/覆盖/乱序；用户消息必然得到正常回复；无"双回复" |
| 用户刚发言（<2 分钟）Worker tick | 不触发（Reactive 优先） |
| 正常回复流式输出期间 tick | WAIT"用户正在对话"，不产生主动消息 |

## 6. 人格一致性（V6.5 联动）

- 主动消息不带【表现方式】段是预期（无用户输入轮），但人格底色必须一致：温柔、克制、不撒娇式索取回应。
- 主动消息**不触发** V5 状态更新/摘要/记忆提取（concurrency.md §4）——观察 emotion_history 无主动轮记录。

## 通过判定

- S1~S5 全部命中；主动消息自然度不合格案例记录 intention 与生成文本，反馈 proactive prompt 迭代。
- 全量 `uv run pytest tests/ -v` 保持全绿。
- 已知非问题：`tests/e2e/test_log_redaction.py` 在 xdist 并行下 caplog 偶发空捕获（复跑即绿，与 V7 无关）。
