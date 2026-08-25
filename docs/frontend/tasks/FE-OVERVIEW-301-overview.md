# FE-OVERVIEW-301 · Overview 面板最小版与 DebugTabs 骨架

## Task ID

FE-OVERVIEW-301

## Task Name

Overview 面板最小版（消费 turn_meta）与 DebugTabs 骨架

## Type

FE

## Priority

P0

## Description

实现 DebugPane 的第一个可用 Tab：在回答开始前即展示本轮 RoleMode 与 TurnAnalysis（数据来自流内 turn_meta，经 chat store 中转），并落地降级徽章规则与「turn_meta 缺失」降级提示。同时搭起 DebugTabs 五 Tab 导航骨架（其余 Tab 占位禁用）。

## Scope

- DebugTabs 组件：Overview/State/Memory/Trace/Raw 五 Tab；本阶段仅 Overview 可用，其余显示占位禁用态；activeTab 存 UiSessionState
- RoleModeCard：mode/intent（Badge 色板）、confidence 数值条、reason 全文
- TurnAnalysisCard：emotion/event/behavior 三枚举 Badge + behavior reason
- 降级徽章规则（前端启发式展示）：router confidence 低于展示阈值或 analysis 呈默认值组合（neutral/daily/normal_reply 且 reason 为空）→ 显示黄色 degraded 徽章「可能已降级」，hover 说明推断依据；阈值常量集中 lib 并注明与后端 settings 对齐关系
- turn_meta 缺失路径：整轮完成仍无 turn_meta → Overview 显示「本轮元数据缺失（旧契约），Phase 2 经 REST 回填」提示
- StateSummaryBar 占位（Phase 2 接 REST 快照）

## Out of Scope

- REST 回填真实状态摘要（API-FE-501 之后）
- Raw JSON 展示（FE-LINK-506 的 RawPanel）
- emotion_history 时间线（FE-STATE-503）

## Dependencies

- FE-CHAT-103（turn_meta 数据落 store）、FE-THEME-002（Badge 色板）

## Input

- 架构文档第 3 节 Tabs 分组表、第 6 节 RoleMode/TurnAnalysis 模型、第 8.1 节 turn_meta 时序
- 后端降级矩阵：`docs/v2/v2-architecture.md` 第 2 节（四条降级链路语义）

## Output

- DebugTabs + OverviewPanel 及其三张卡 + 降级规则常量

## Business Rules

- Overview 渲染不得阻塞或延迟聊天渲染（同屏两栏独立更新）
- turn_meta 在首个 delta 前到达时卡片即时可见（架构卖点：回答开始前即可观测路由结果）
- 降级徽章是「启发式提示」不是断言：文案必须带「可能」措辞，避免误导调试者

## API Dependencies

- 无直接调用；消费流内 turn_meta 事件

## Data Dependencies

- chat store 中由 FE-CHAT-103 写入的当前轮 meta 位

## Permission

- 同全局：无鉴权

## Error Handling

- 字段残缺（如缺 reason/confidence）时对应区块显示占位符，不抛错不空窗

## Acceptance Criteria

- Mock 剧本 1/2/3：三卡枚举 Badge 色、reason 文本正确
- Mock 剧本 5（无 turn_meta）：出现降级提示且不报错
- 含默认值组合的剧本出现黄色 degraded 徽章

## Test Requirements

- 组件测试：给定 turn_meta 对象断言卡片内容与徽章态
- 缺失/残缺字段用例各一
