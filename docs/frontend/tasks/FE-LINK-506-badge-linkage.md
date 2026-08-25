# FE-LINK-506 · TurnBadge 消息↔Trace 联动与 RawPanel

## Task ID

FE-LINK-506

## Task Name

TurnBadge 消息徽章、双向联动选中与 RawPanel 原始终稿

## Type

FE

## Priority

P1

## Description

实现 Debug Console 区别于普通 Chat UI 的核心交互：每条 AI 消息挂「本轮徽章」（mode·behavior·总耗时），点击消息 ↔ 右侧 Trace 双向联动；并提供 Raw Tab 查看整轮原始数据终稿。

## Scope

- debugSlice 扩展：selectedTurnId / selectedStepId / activeTab 联动动作
- TurnBadge：AI 消息气泡下缘徽章，内容 = mode + behavior + totalMs（mono）；该轮 trace 未加载时显示骨架占位宽度
- 联动行为：点击消息/徽章 → selectedTurnId 置为该轮 → DebugPane 自动切到 Trace Tab 并加载该轮快照；点击 Trace 详情中 LLM 步输出 → 高亮对应 AI 消息（反向联动，滚动到可见）
- RawPanel：整轮原始终稿展示——本轮请求体、事件序列（流内收到的原始行）、turn trace 快照 JSON，分三区块折叠，各配 JsonViewer 与 copy
- 折叠回 Chat 全宽时点击徽章自动展开 DebugPane

## Out of Scope

- user 消息的徽章（无独立轮次观测价值）
- 多轮并排对比

## Dependencies

- FE-TRACE-505（Trace Tab 就绪）、FE-CHAT-103/104（store 选中态与消息渲染位）

## Input

- 架构文档第 3 节修正点 3（灵魂交互定义）、第 10 节多轮组织

## Output

- TurnBadge 组件、debugSlice 联动逻辑、RawPanel

## Business Rules

- 联动是「选择」不是「导航」：不产生路由跳转、不丢失滚动位置
- 反向高亮不得触发 AutoScroll 抢夺（仅 MessageList 内部 scrollIntoView）
- turn_id 缺失的旧消息徽章显示灰色占位「—」，点击提示该轮无观测数据

## API Dependencies

- 间接消费 useTurnTrace（经 505 已建立的通道）

## Data Dependencies

- chat store（消息列表、各轮 turn_meta/turn_id 记录）、debugSlice 选中态

## Permission

- 同全局：无鉴权

## Error Handling

- 该轮快照 404 时徽章仍可点击，Trace 面板呈现既有 not-found 态（不重复处理）

## Acceptance Criteria

- 连续三轮对话后：点任一消息 → 右侧切到该轮 Trace 且数据正确；反向点击 LLM 步 → 左侧消息高亮
- DebugPane 折叠态下点击徽章自动展开并定位
- RawPanel 三区块内容完整可 copy

## Test Requirements

- 集成交互测试：正向/反向联动、折叠展开恢复、RawPanel 渲染
