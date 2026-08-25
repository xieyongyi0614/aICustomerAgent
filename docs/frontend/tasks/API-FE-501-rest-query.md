# API-FE-501 · REST Client、TanStack Query 集成与有界轮询策略

## Task ID

API-FE-501

## Task Name

REST 端点封装、Query 基座与 done 后有界轮询 + 惰性刷新策略

## Type

API

## Priority

P1

## Description

实现 D-F2 的 Debug 数据通道：四个只读端点的 REST 封装、TanStack Query 接入、以及「done 后有界轮询 → complete 即停 / 惰性刷新 / 手动刷新」三种获取方式的统一收敛。全部以 MSW 为先行验收环境，真实联调在汇合点 I2。

## Scope

- `api/rest.ts`：GET state / GET conversations/{id}/messages / GET memories / GET debug turns trace 四端点封装（复用 API-FE-101 的 http 底座与 ApiError）
- QueryClient Provider 接入 app/providers；缓存键约定（queryKey 规范：[资源, 参数]）
- hooks：useTurnTrace(turnId)——done 后启动有界轮询（间隔约 800ms、最多约 6 次、见 status=complete 即停、404 即停并提示）；useCharacterState / useMemories / useConversationMessages——常规 query
- 惰性刷新语义：面板挂载/turnId 变化时 refetchOnMount；暴露手动 refetch 供刷新按钮（FE-TRACE-505 头部）使用
- MSW 基座：worker 初始化 + 四端点 handlers 最小实现（fixtures 由 TEST-SCENE-601 扩充，本任务内置最小可用集）

## Out of Scope

- 面板 UI（503~506）
- fixtures 场景扩充（TEST-SCENE-601）
- 写操作端点（不存在）

## Dependencies

- ARCH-FE-001（工程）、API-FE-101（http 底座）
- **并行标记**：契约依赖 BE-API-402/403/404，但开发验收以 MSW 为准，全程不阻塞；I2 完成真机回归

## Input

- 架构文档第 8.2 节（获取策略三原则）、附录 A2 字段清单
- BE-API 各任务产出的响应 DTO 说明

## Output

- rest.ts + 四个 hooks + QueryProvider + MSW handlers 最小集

## Business Rules

- 轮询必须有界：任何情况下不超过上限次数，超时后在界面呈现「后处理未完成」而非无限转圈
- turn trace 缓存按 turnId 隔离；complete 后视为不可变数据不再自动 refetch
- Mock/Real 行为完全一致（组件无感），MSW 只在 mock mode 启用

## API Dependencies

- GET /api/v1/state、GET /api/v1/conversations/{id}/messages、GET /api/v1/memories、GET /api/v1/debug/turns/{id}/trace

## Data Dependencies

- 无本地持久化；Query 缓存即数据层

## Permission

- 同全局：无鉴权

## Error Handling

- 404（turn 被淘汰）：停止轮询，hook 返回明确 not-found 态供面板提示「重发一轮以采集」
- 网络/500：Query 默认重试一次后落错误态，面板显示局部错误卡片（铁律三：不拖垮其他面板）

## Acceptance Criteria

- MSW 下：pending→complete 流转正确驱动轮询并在 complete 停止（网络层计数验证）
- 轮询超时上限生效且有兜底文案
- 手动刷新按钮位可触发 refetch（按钮本身在 505）

## Test Requirements

- hook 测试（MSW）：complete 直返、pending 轮询至完成、超时停止、404 停止四用例
- queryKey 冲突冒烟（不同 turnId 不串缓存）
