# FE-ACTION-507 · Retry 重发与 Clear Conversation

## Task ID

FE-ACTION-507

## Task Name

Retry（重发上一轮）与 Clear Conversation（确认后新建会话）

## Type

FE

## Priority

P1

## Description

补齐会话级操作：失败或不满意的回答一键重发上一条用户输入；清空当前会话（Dialog 确认）。两者都只做前端语义操作，不做后端删除。

## Scope

- Retry：取最近一条 human 消息内容重发；重试目标轮的 ai 消息从列表移除（含其 error/stopped 残骸），重新走 send 流程；streaming 中 Retry 禁用
- Retry 入口：错误消息上的快捷按钮 + 输入栏旁全局按钮双入口
- Clear：ConversationHeader 的 Clear 按钮 → Dialog 二次确认（列明影响范围=本地视图清空+切换新 session，后端数据保留）→ 确认后等价新建会话（复用 TopBar 的 new-session 动作）
- 清空后 AutoScroll 重置跟随态（与 FE-CHAT-106 约定一致）

## Out of Scope

- 后端消息删除 / 会话删除端点
- 消息编辑后重发

## Dependencies

- FE-CHAT-103（send 动作复用）、FE-TOPBAR-004（new-session 动作复用）

## Input

- 架构文档第 12 节「应该做」清单

## Output

- Retry/Clear 交互逻辑与 UI 接线

## Business Rules

- Retry 永远针对「最后一轮」，且以 human 消息原文为准（不以草稿框内容为准）
- Clear 必须二次确认；确认前不做任何破坏性动作
- 重发产生的轮次是全新 turn：新 turn_id、新 trace，旧轮数据不再引用

## API Dependencies

- 经由 useChat 的既有发送链路，无新端点

## Data Dependencies

- chatSlice.messages（定位最后一轮）

## Permission

- 同全局：无鉴权

## Error Handling

- 无可重试目标（空会话）时按钮禁用；Clear 在 streaming 中禁用（先 Stop 再 Clear，UI 引导文案提示）

## Acceptance Criteria

- 错误剧本后 Retry 成功重发且旧残骸移除、新轮正常完成
- Clear 流程含确认弹窗，取消无副作用；确认后界面回到全新会话态
- streaming 中两操作均被正确禁用

## Test Requirements

- 交互测试：Retry 链路、Clear 确认/取消两分支、禁用态矩阵
