# LLM 调用链路图

> 一轮用户消息（`POST /api/v1/chat/message`）触发的全部 LLM 调用清单与流程。
> 代码入口：`apps/backend/app/application/chat_pipeline.py`（前台）、`apps/backend/app/application/post_process.py`（后台）。
> 设计原则（`docs/version/v2.0.0/architecture/llm-orchestration.md`）：规则 → 数据库查询 → Embedding → LLM；goal_review / mode 稳定 / behavior_engine / intention_policy 均为纯规则，零 LLM。

## 总览

| 阶段 | 调用数 | 说明 |
|---|---|---|
| 前台（用户等待期） | 4 并行 + 1 串行 = **5 次** | 4 个小链并行 + 回答流式生成 |
| 前台 fallback 放大 | **+0~4 次** | 结构化链主调用失败时走 PydanticOutputParser 兜底，重发完整请求 |
| 后台（SSE 不等待） | **0~5 次** | scene_update / state_update / summary（达阈值）/ memory_extract / evaluation judge（采样命中） |
| 非对话路径 | 按触发 | V7 主动行为 proactive_chain、V2 反思 reflector |

## 流程图

> 拆成 3 张图查看：图 1 全局骨架（最简）；图 2 前台详情；图 3 后台详情。

### 图 1 · 全局骨架

```mermaid
flowchart TD
    U["用户消息<br/>POST /api/v1/chat/message"] --> FG
    U --> BG

    subgraph FG["前台 · 用户等待期（chat_pipeline.py）"]
        P1["①~④ 四链并行<br/>router / turn_analysis / scene_intent / intention"]
        P2["⑤ answer_chain.astream<br/>流式回复生成"]
        P1 --> P2
    end

    subgraph BG["后台 · SSE 不等待（post_process.py）"]
        S1["9 步顺序执行<br/>scene_update → state_update → goal_review → summary<br/>→ memory_extract → budget → evaluation → world → action"]
    end

    style P1 fill:#e8f0fe
    style P2 fill:#fff3cd
    style S1 fill:#d4edda
```

### 图 2 · 前台详情（4 并行 + 1 串行）

```mermaid
flowchart TD
    CB["context_builder 构建状态<br/>goal_service.select 目标选择<br/>（均 0 LLM，纯规则）"]

    CB --> PAR

    subgraph PAR["asyncio.gather 四链并行"]
        R1["① router_chain<br/>RoleMode<br/>模式路由候选"]
        R2["② turn_analysis_chain<br/>TurnAnalysis<br/>情绪/事件/行为"]
        R3["③ scene_intent_chain<br/>SceneIntentResult<br/>场景意图分类"]
        R4["④ intention_chain<br/>IntentionDecision<br/>角色本轮意图"]
    end

    R1 --> MS["mode 稳定器<br/>（0 LLM）"]
    R2 --> RA["失败 → 默认分析<br/>（degraded）"]
    R3 --> SR["场景收敛<br/>（0 LLM）"]
    R4 --> IP["意图校验<br/>（0 LLM）"]

    MS --> BE["behavior_engine<br/>行为策略（0 LLM）<br/>detect_action_intent 行动检测"]
    RA --> BE
    SR --> BE
    IP --> BE

    BE --> A5["⑤ answer_chain.astream<br/>流式回复生成（LLM）<br/>注入情绪/场景/目标/行为/世界上下文"]
    A5 --> SAVE["消息落库 → SSE done"]
    SAVE -.->|"schedule_post_process"| BG3(["后台 9 步（见图 3）"])

    style R1 fill:#e8f0fe
    style R2 fill:#e8f0fe
    style R3 fill:#e8f0fe
    style R4 fill:#e8f0fe
    style A5 fill:#fff3cd
```

### 图 3 · 后台详情（9 步顺序执行，独立容错，失败不冒泡）

```mermaid
flowchart TD
    B1["scene_update_chain ✅LLM<br/>SceneActionDecision<br/>场景动作更新"]
    B2["state_update_chain ✅LLM<br/>StateUpdateDecision + 确定性规则<br/>情绪/energy/V5 关系动力学"]
    B3["goal_service.review<br/>❌纯规则"]
    B4{"summary<br/>消息数 ≥ 40？"}
    B5["summary_chain ✅LLM<br/>滚动摘要压缩"]
    B6["extractor_chain ✅LLM<br/>MemoryExtraction<br/>长期记忆提取"]
    B7["budget_observer ❌纯规则"]
    B8{"evaluation judge<br/>采样命中？"}
    B9["evaluation_judge_chain ✅LLM<br/>回复质量评估"]
    B10["world_engine<br/>世界状态推演"]
    B11["action_engine<br/>行动规划（条件触发）"]

    B1 --> B2 --> B3 --> B4
    B4 -->|是| B5 --> B6
    B4 -->|否| B6
    B6 --> B7 --> B8
    B8 -->|命中| B9 --> B10
    B8 -->|未命中| B10
    B10 --> B11

    style B1 fill:#d4edda
    style B2 fill:#d4edda
    style B5 fill:#d4edda
    style B6 fill:#d4edda
    style B9 fill:#d4edda
```

图例：🔵 淡蓝 = 前台四并行链；🟡 黄 = 回答生成；🟢 绿 = 后台 LLM 步骤；✅LLM / ❌纯规则 标注是否产生调用。

## 放大系数：结构化链 fallback

所有结构化链（① ② ③ ④ 及后台 B1/B2/B6）由 `chains/structured.build_structured_chain` 构建：

```
primary = prompt | model.with_structured_output(schema)
chain   = primary.with_fallbacks([fallback_prompt | model | PydanticOutputParser])
```

主链失败（解析失败 / `LengthFinishReasonError` 等）→ **立即重发一次完整请求**走兜底解析。
即：每次主链失败，该步骤的调用数 ×2。典型场景是思考型模型 `max_tokens` 过小导致 reasoning 耗尽预算被截断。

## 一轮的调用数速查

| 场景 | 调用数 |
|---|---|
| 最少（所有后台条件不命中、无失败） | 5 |
| 典型（scene_update + state_update + memory_extract） | 8 |
| 全触发（+summary 达阈值 + judge 采样命中） | 10 |
| 有 1 个结构化链失败走 fallback | +1/次失败 |
