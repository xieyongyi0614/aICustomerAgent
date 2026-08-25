# TEST-SCENE-601 · MSW 场景剧场完善

## Task ID

TEST-SCENE-601

## Task Name

MSW REST fixtures 场景库与异常边界剧本完善

## Type

TEST

## Priority

P2

## Description

把 Mock 体系从「最小可用」升级为「调试剧场」：三套 persona fixtures + 异常边界场景全覆盖，使前端所有面板在无后端环境下可演示、可回归。

## Scope

- REST fixtures 三套 persona：
  1. 空状态用户（无记忆、默认状态值、无 emotion_history）
  2. 富状态用户（多维记忆、中期关系数值、完整情绪历史）
  3. 临升级用户（三维贴近 close_friend 阈值、近期 achievement 序列）
- 异常边界 handlers：state/memories 500、trace pending 持续超时、trace 404（已淘汰）、messages 空会话、网络延迟模拟
- 与 FE-MOCK-102 流剧本的组合场景：诉苦剧本 × 富 persona（一轮对话后的完整面板数据自洽）
- 数据自洽校验：fixture 数值满足领域约束（0–1 区间、stage 与阈值关系成立）

## Out of Scope

- 性能压测用途的海量数据构造
- 真实后端 e2e（属各自 BE 任务的测试职责）

## Dependencies

- FE-MOCK-102、API-FE-501

## Input

- 架构文档第 9 节 Mock Architecture
- V2 架构文档第 4 节规则表（保证 fixture 数值符合 delta/阈值语义）

## Output

- mocks/ 下扩充后的 handlers + fixtures 集
- 场景清单说明（每个 handler 对应的验证目的）

## Business Rules

- fixture 必须通过 domain 类型校验（编译期保证）
- 异常场景必须可通过显式开关（如特殊 query 参数或独立 handler 路径）稳定触发，不允许随机性导致用例抖动

## API Dependencies

- 模拟对象：GET state / messages / memories / turns trace 四端点

## Data Dependencies

- 无真实数据依赖

## Permission

- 不适用（测试基座）

## Error Handling

- 本任务即错误路径的生产者：每个错误 handler 附预期断言说明

## Acceptance Criteria

- 切 mock mode 后：三个面板在三套 persona 下渲染正确（人工走查清单）
- 每个异常场景可在 UI 触发对应的错误态/超时态/空态呈现
- 组合场景数据自洽（聊完诉苦剧本后 State/Memory/Trace 数值变化方向合理）

## Test Requirements

- fixture 校验单测（类型 + 领域约束断言）
- 各异常 handler 的响应契约断言
