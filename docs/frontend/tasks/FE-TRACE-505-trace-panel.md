# FE-TRACE-505 · TraceWaterfall 时间轴与步骤详情

## Task ID

FE-TRACE-505

## Task Name

TracePanel：sqrt 缩放 Waterfall、降级标记与步骤详情区

## Type

FE

## Priority

P1

## Description

实现 Debug Console 的招牌组件：单轮 Trace 的垂直 Waterfall 时间轴（渲染自 REST 整轮快照）+ 点击步骤的详情区。设计要点全部来自架构文档第 10 节。

## Scope

- TraceWaterfall：
  - 每步一行：步骤名 + 相对时长条 + 绝对 ms（mono）+ 状态点（ok 绿/warn 黄+degraded 徽章/error 红）
  - 时长条 sqrt 缩放（防止 LLM 数秒压扁其余步骤），hover tooltip 显精确值与占比
  - 并发步骤共享起始坐标（role_router 与 turn_analyzer 同起点；依据 steps 序与已知并发关系常量表布局）
  - 后处理步骤（state_update/memory_extractor）虚线边框并与主体分隔，表达「done 之后异步完成」
  - 头部汇总行：totalMs、步骤数、降级计数、手动刷新按钮（接 API-FE-501 的 refetch）
- TraceStepDetail：选中步的 Input/Output（JsonViewer）、Duration/Status（warn 附原因）、Error 红块 + copy
- pending 态：头部显示「后处理进行中…」与轮询中的骨架行；complete 后填充
- 404/淘汰态：提示「该轮数据已被清理，重发一轮以采集」

## Out of Scope

- DAG/拓扑图渲染（LangGraph 期再评审）
- 跨轮对比视图

## Dependencies

- API-FE-501（useTurnTrace）、FE-JSON-502、FE-THEME-002、FE-LAYOUT-003

## Input

- 架构文档第 10 节（完整设计规格）、附录 A3 步骤名枚举
- BE-API-404 DTO（steps 序稳定约定）

## Output

- TracePanel / TraceWaterfall / TraceStepDetail + 缩放与并发布局工具函数（lib，纯函数便于单测）

## Business Rules

- 步骤名按后端固定枚举渲染，未知步骤名追加显示在末尾并以中性样式呈现（前向兼容 LangGraph 新 node）
- durationMs=0 或缺失的步骤渲染最小时长条占位，不留空白行
- 降级徽章必须醒目（铁律一：不允许静默降级看起来正常）

## API Dependencies

- GET /api/v1/debug/turns/{turn_id}/trace（经 useTurnTrace 含轮询）

## Data Dependencies

- TurnTrace 快照（steps/meta/status）

## Permission

- 同全局：无鉴权

## Error Handling

- steps 为空数组：空态说明「该轮早于采集器上线或数据被清理」
- 单步 error 详情缺 error 文本时显示 status 占位说明

## Acceptance Criteria

- 用构造 steps（含 LLM 4820ms 极端占比、并发两步、一个 degraded、一个 error）渲染：缩放比例、同起点、虚线分隔、徽章全部正确
- 点击行切换详情区内容；pending→complete 自动填充
- 三种异常态（空/pending 超时/404）各有正确呈现

## Test Requirements

- 纯函数单测：sqrt 缩放宽度计算、并发起点计算
- 组件测试：上述构造数据的渲染断言 + 详情切换交互
