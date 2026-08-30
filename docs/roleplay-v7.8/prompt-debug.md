# M3 Prompt Debug System

> 目标：回答"哪个 Prompt 影响模型"——记录最终发送给 LLM 的上下文快照，支持查看、比较、定位。
> 铁律：**禁止默认保存全部生产 Prompt**。采样 + debug 开关 + 保留策略三重控制；采集绝不改变发出的 prompt 字节。

## 1. PromptSnapshot 域模型

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str | uuid hex |
| request_id | str | 关联 trace |
| turn_id | str \| None | 关联评估主体（AI 消息 id） |
| call_site | CallSite | answer / router / turn_analysis / scene_intent / intention / scene_update / state_update / extractor / summary / proactive / judge |
| profile_id / model | str | 该次调用实际使用的 profile 与模型名 |
| messages | list[dict] | 最终 messages（role + content）；总字符受 `observability_prompt_max_chars`（默认 20000）截断，打 `truncated: true` |
| section_budget | dict \| None | 仅 answer：各 section 字符占用与裁剪标记，见 §3 |
| truncated | bool | |
| created_at | datetime | |

## 2. 采集点（三个，全部在组装完成之后）

| 采集点 | 位置 | 拿到什么 |
|---|---|---|
| 生成链 | `app/chains/answer_chain.py`（PromptBuilder.build 之后、astream 之前） | 最终 messages + section 预算报告 |
| 结构化链 | `app/chains/structured.py::build_structured_chain`（全部 7 条辅助链 + judge 的统一入口） | 解析后的 messages——一处拦截覆盖全部辅助调用 |
| 普通链 | `app/chains/summary_chain.py`、`proactive_chain.py` | 调用入口处的 messages |

采集即**暂存**：快照对象挂到 TraceSession 的有界缓冲区，随 `on_turn_finished` 一并 flush；单独的后台调用（judge）在调用点直接交 Facade。热路径上只有"把已有对象引用存进列表"级别的开销。

## 3. section_budget：定位"哪个 Prompt 影响模型"

answer prompt 由 `PromptBuilder.build`（`app/prompts/builder.py:154`）按 identity → emotion / state / relationship → goal / intention / behavior → memory → summary → history → tail 顺序组装，再经 `_fit_variable_parts`（:129）按 `context_total_char_budget=12000` 裁剪。快照从 builder 产出的模板变量**只读**统计：

```json
{
  "identity": 1830, "emotion": 220, "memory": 4100, "summary": 900,
  "history": 3100, "tail": 480, "total": 10630, "budget": 12000,
  "clipped": ["memory", "history"]
}
```

`clipped` 列表直接回答"记忆是不是被裁掉了所以角色没想起来"这类问题；与 M6 关联后，"MISSED（漏用记忆）issue"可以直接对照 memory section 是否被裁剪。

## 4. 采样与保留（三重控制）

| 控制 | 配置 | 默认 |
|---|---|---|
| 模式 | `observability_prompt_capture_mode` = disabled / sampled / always | **sampled** |
| 采样率 | `observability_prompt_sample_rate`，request_id 确定性哈希（同 M1 口径） | **0.2**——默认只留五分之一，满足"禁止默认保存全部生产 Prompt" |
| 上限 | `observability_prompt_max_chars` | 20000 字符，超限截断 |
| TTL | `observability_prompt_retention_days` | **3 天**（最短寿命的数据） |

调试需要全量时：`.env` 设 `OBSERVABILITY_PROMPT_CAPTURE_MODE=always`，改完即生效（settings 读取点在采集判定处）。生产建议 disabled 或进一步降采样。

## 5. 三个能力

### 查看
`GET /debug/turns/{turn_id}/prompts` — 该轮全部快照（按 call_site 分组）；`GET /debug/prompts/{id}` — 单条。

### 比较（011）
`GET /debug/prompts/compare?a={id}&b={id}` — 结构化 diff：

```json
{
  "model_changed": {"a": "glm-4.7", "b": "minimax-m3"},
  "total_chars": {"a": 10630, "b": 11890},
  "section_diff": {"memory": {"a": 4100, "b": 5300}},
  "clipped_changed": {"a": [], "b": ["memory"]},
  "messages_count": {"a": 9, "b": 11}
}
```

典型用法：同一会话相邻两轮快照对比，定位"为什么这轮行为变了"——是记忆段膨胀、历史变长还是模式指令切换。

### 定位
`section_budget.clipped` + M6 关联：低分评估 → 该轮 answer 快照 → 被裁剪的 section → 复盘 prompt 策略问题（V7.8 只呈现事实，不改策略）。

## 6. 边界

- **采集不改变 prompt 字节**：`tests/golden/` 金样测试在 V7.8 全程必须字节不变，这是本模块的机器可证底线。
- 不为快照改造 PromptBuilder 的输出结构；section 统计是读模板变量，不是让 builder 多吐一份报告对象（若实现时确需 builder 暴露只读统计方法，方法本身不得影响 build 返回值）。
- 不存 judge prompt 的完整原文（沿用 V7.5"不存 judge prompt"约束）——judge 的 call_site 快照只记 schema/模型/耗时，messages 置空。
