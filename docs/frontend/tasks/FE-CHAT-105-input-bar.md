# FE-CHAT-105 · 输入栏 Send / Stop 交互

## Task ID

FE-CHAT-105

## Task Name

ChatInputBar：textarea、Send ⇄ Stop 切换与防抖保护

## Type

FE

## Priority

P0

## Description

实现聊天输入栏：多行文本输入、键盘发送约定、发送中按钮切换为 Stop。是调试者的主要操作面。

## Scope

- textarea 自适应高度（设上限后内部滚动）
- Enter 发送 / Shift+Enter 换行；IME 组合输入期间 Enter 不触发发送
- Send 按钮 ⇄ Stop 按钮：由 store 的 streaming 态驱动；Stop 调用 useChat.stop()
- 空输入 / 纯空白禁用 Send；streaming 中禁用 Send（store 层已有防御，此处同步 UI 态）
- 输入草稿 useState 本地保存（不持久化）

## Out of Scope

- Retry 按钮（FE-ACTION-507）
- AutoScroll 开关控件（FE-CHAT-106）
- 斜杠命令、@提及等增强

## Dependencies

- FE-CHAT-103

## Input

- 架构文档第 5 节组件树（ChatInputBar/SendControls 职责）

## Output

- ChatInputBar 组件（含 SendControls）

## Business Rules

- streaming 态下 Enter 与 Send 点击均不产生新请求
- 发送成功后清空草稿；发送被拒绝（store 防御触发）不清空草稿

## API Dependencies

- 无直接调用（动作全部经由 useChat）

## Data Dependencies

- chatSlice.streaming 状态、sessionSlice

## Permission

- 同全局：无鉴权

## Error Handling

- 发送失败不清空草稿，便于直接重试

## Acceptance Criteria

- IME 组合词回车不上送（中文输入法场景必测）
- 连续快速点击 Send 只发出一轮请求
- Stop 即时生效（配合 103 验收）

## Test Requirements

- 交互测试：键盘流、按钮态流转、连点防护
