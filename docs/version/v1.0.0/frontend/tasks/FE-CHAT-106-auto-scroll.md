# FE-CHAT-106 · AutoScroll 跟随与上滚暂停

## Task ID

FE-CHAT-106

## Task Name

MessageList 自动滚动跟随、上滚暂停与「回到底部」浮标

## Type

FE

## Priority

P0

## Description

实现架构文档要求的 AutoScroll 行为：默认跟随流式输出滚到底部；用户向上滚动即暂停跟随并浮现「回到底部」浮标。这是「边看 Trace 边聊天」体验成立的前提（铁律：Debug 不拖慢 Chat）。

## Scope

- hooks/useAutoScroll：监听 MessageList 滚动容器，判定「贴近底部」阈值（如距底 < 40px）
- 跟随模式：新内容到达且处于跟随态时平滑滚底
- 上滚脱离跟随态；再次手动滚到底部或点击浮标恢复跟随态
- 「回到底部」浮动按钮（含未读新增行数提示可选）
- 输入栏区域提供跟随态开关（AutoScroll✓，架构 MVP 清单项），关闭后永不自动滚底

## Out of Scope

- 消息虚拟滚动（Phase 3 FE-POLISH-602 评估）
- Trace 面板内的滚动（面板自管）

## Dependencies

- FE-CHAT-104

## Input

- 架构文档第 12 节 MVP 必须项（AutoScroll 必须带上滚暂停）

## Output

- useAutoScroll hook + 浮标组件 + 开关接线

## Business Rules

- 用户上滚期间，任何流式增量都不得强行拉回底部（硬性体验规则）
- 恢复跟随时一次性直达底部（不做逐帧追赶动画拖延）
- 会话清空/新建后重置为跟随态

## API Dependencies

- 无

## Data Dependencies

- chatSlice.messages（新内容信号）

## Permission

- 同全局：无鉴权

## Error Handling

- 滚动容器缺失/卸载时 hook 静默失效，不抛错

## Acceptance Criteria

- 流式中手动上滚：视口保持不动且浮标出现；点浮标回底并恢复跟随
- 关闭 AutoScroll 开关后全程不自动滚动
- 快速连续输出下跟随不抖动、不掉队

## Test Requirements

- 交互测试：上滚暂停/恢复/开关三链路
- 阈值边界用例（贴底 vs 离底 1px）
