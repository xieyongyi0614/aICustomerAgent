# v2.0.0 LLM Orchestration

> 原则：**不要让每个步骤都调用 LLM。** 顺序：规则 → 数据库查询 → Embedding → LLM。LLM 是 Runtime 内部的 Reasoning / Generation / Evaluation 三个引擎。

## 1. LLM 任务总清单（逐项裁决）

| 任务 | v1 现状 | v2 裁决 | 是否必须 LLM | 执行时机 |
|---|---|---|---|---|
| 路由 router | LLM | **合并**入 turn_analysis 单次调用（小模型） | 否（可规则兜底，保留 LLM 提精度） | 前台 |
| 轮次分析 turn_analysis | LLM | 保留，小模型 | 是 | 前台 |
| 场景意图 scene_intent | LLM | 保留，小模型 | 是（歧义场景） | 前台 |
| 意图 intention | LLM | 保留，小模型 + 规则 Policy | 是（歧义时） | 前台 |
| **回答 answer** | LLM 主力 | 保留，主力模型，流式 | 是 | 前台 |
| 状态更新 state_update | LLM | 保留，小模型 | 是（情绪归类） | 后台 |
| 记忆抽取 extractor | LLM 全量 | **规则预筛 + LLM 兜底**（低显著度对话 0 调用），小模型 | 部分 | 后台 |
| 记忆转正判定（新） | — | 规则打分先行；仅不确定样本调 LLM | 部分 | 后台 |
| Embedding（新） | — | 批量异步，非 LLM chat | — | 后台批 |
| 摘要 summary | LLM 阈值触发 | 保留 | 是 | 后台 |
| 场景更新 scene_update | LLM（有场景时） | 保留，小模型 | 是 | 后台 |
| Evaluation Judge | LLM 采样 | 保留采样 | 是 | 后台 |
| **Reflection（新）** | — | 证据门槛达标才调；每日 + 事件触发，低频 | 是 | 后台周期 |
| **Goal Planning（新，P6）** | — | 目标创建/重规划时调用，低频 | 是 | 后台 |
| 主动消息 proactive | LLM | 保留（命中 AutonomyPolicy 才调） | 是 | 后台 |
| World 解释 world_llm_assist | 默认关 | 维持默认关 | 否 | — |
| 关系信号 rel_signal_llm | 默认关 | 维持默认关（启发式够用） | 否 | — |

## 2. 模型分层（两档）

| 档 | 用途 | 特点 |
|---|---|---|
| **主力（main）** | answer、proactive、Reflection、Goal Planning | 长 context、高质量 |
| **轻量（lite）** | router/turn_analysis/scene_intent/intention/state_update/extractor 兜底/scene_update/Judge | 快、便宜；同一 OpenAI 兼容网关下配置第二个 profile |

`llm_factory` 扩展为按任务类型取 profile；不建多模型路由平台。

## 3. 成本治理

| 手段 | 说明 |
|---|---|
| 链合并 | router+turn_analysis 合一（同一 prompt 两输出），前台并行 4 链 → 3 链 |
| 规则预筛 | 记忆抽取/转正、Reflection 门槛、Idle 判定——规则说不需要就不调 |
| 后台全异步 | 除 answer 外无前台 LLM |
| 批处理 | embedding、Judge 采样、后台小模型任务按批合并窗口 |
| 缓存 | 同轮内重复检索结果缓存；Persona 系统段前缀缓存（网关支持则启用） |
| **预算熔断** | 全局每日 LLM Token/调用配额（settings 可调），超限后台任务降级为「只记 Candidate 不评估」；前台永不熔断 |
| 记账 | llm_call_records 已有 cost/tokens，按任务类型打 tag 汇总报表 |

## 4. 目标指标

| 指标 | v1 基线 | v2 目标 |
|---|---|---|
| 前台 LLM 调用/轮 | 5 | ≤ 4（router 并入 turn_analysis 后 3 链 + answer；无歧义轮次链路可短路至 2） |
| 后台 LLM 调用/轮 | 3–5 | 1–3（规则预筛后） |
| 后台周期任务 LLM | — | 反思 ≤ 1 次/日/用户（正常态） |
| Token 成本/轮 | 基线 | ≤ 基线 × 1.2（含后台新增，超线触发重审） |

## 5. 失败与降级

- 轻量模型不可用 → 规则兜底路径（v1 已有 intention_policy/mode_service 模式，全链保持）。
- 主力模型不可用 → answer 返回明确错误（不静默编造）；后台任务进重试队列（background_jobs，指数退避）。
- Judge 超时/失败 → 该轮评估记 skipped，不阻塞（沿 v1）。
