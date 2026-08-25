# BE-TRACE-401 · Agent Trace 步骤采集器

## Task ID

BE-TRACE-401

## Task Name

编排全链路步骤耗时与状态采集（旁路观测，随轮可查）

## Type

BE

## Priority

P1

## Description

在 stream_chat 编排的各环节埋点，采集每步 durationMs 与 status(ok|degraded|error)，随 turn 可查询。这是 Debug Console Trace 面板的数据源头。设计为纯旁路：埋点失败不影响主流程。

## Scope

- 步骤名固定枚举（架构文档附录 A3）：role_router / turn_analyzer / memory_retrieval / context_builder / prompt_builder / llm（含 first_token_ms）/ state_update / memory_extractor
- 采集器模块（services 下新建轻量模块）：start/end 记录、status 标注（degraded 判定来源：router 低置信、analysis 默认值、StateUpdater 规则兜底——复用 V2 已有的降级发生点）、llm 步额外记录首 token 延迟
- 存储：进程内存 dict 按 turn_id 保留最近 N 轮（N 进 `core/settings.py`），LRU 淘汰；不建表、不走 Alembic（DB 类型任务因此为空）
- input/output 本阶段只存摘要或省略（防膨胀），结构预留完整字段位
- 与 BE-TURNMETA-201 的 turn_id 同源

## Out of Scope

- HTTP 端点（BE-API-404）
- 持久化到数据库
- LangGraph 化改造（仅保证步骤名与未来 node 同构）

## Dependencies

- 无前置；下游 BE-API-404 依赖本任务；**与前端并行**

## Input

- `apps/backend/app/services/agent_service.py`（V2 编排现状与各降级点位置）
- 架构文档第 10 节、附录 A3；V2 架构文档第 2 节降级矩阵

## Output

- trace 采集模块 + 编排埋点接入 + settings 新增容量参数
- 内存数据结构可被仓储式接口读取（供 404 使用）

## Business Rules

- 旁路铁律：采集器任何异常被 try/except 吞掉并记日志，绝不影响对话主流程与后处理落库
- 后处理步骤（state_update/memory_extractor）发生在 done 之后异步完成，采集器需支持「步骤晚于回合主体写入」的时序
- 步骤名是稳定契约，禁止随意改名（前端 waterfall 依赖）

## API Dependencies

- 无（被 404 消费）

## Data Dependencies

- 只读编排过程中的局部变量与既有判定结果；不新增 DB 访问

## Permission

- 沿用后端现状

## Error Handling

- 全部埋点点位 try/except 隔离；单步计时失败该步标记 error 而非中断采集

## Acceptance Criteria

- FakeLLM 下完整一轮：8 个步骤全部有记录，durationMs>0，llm 步含 first_token_ms
- 人为触发 router 降级：role_router 步 status=degraded
- 连续多轮超过容量 N：最旧轮次被淘汰，服务不泄漏内存
- 全量 pytest 通过，pylint 达标

## Test Requirements

- 单测：步骤记录完整性、LRU 淘汰、降级标注、异常注入不影响主流程
