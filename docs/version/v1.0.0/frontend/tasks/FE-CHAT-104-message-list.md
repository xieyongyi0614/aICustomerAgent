# FE-CHAT-104 · MessageList / MessageItem / StreamingText 渲染

## Task ID

FE-CHAT-104

## Task Name

消息列表与流式消息渲染

## Type

FE

## Priority

P0

## Description

实现 ChatPane 的消息呈现层：滚动列表容器、human/ai 两种消息形态、流式中的光标与增量文本渲染、错误/停止终态样式。纯渲染组件，从 store 读数据，不含任何请求逻辑。

## Scope

- MessageList：ScrollArea 容器，订阅 messages 列表；空会话引导文案（提示可输入的第一句话）
- MessageItem：human 右侧/ai 左侧的气泡区分（暗色高密度风）；时间戳显示（相对时间工具放 lib）
- StreamingText：status=streaming 时尾部光标动画、内容随 store 增量更新
- 终态样式：error 消息红色边框 + 错误摘要行；stopped 消息灰色「已停止」标记
- 性能约束落地：MessageItem 用稳定 id 作 key；流式仅重渲当前流式项（selector 验证）

## Out of Scope

- TurnBadge 与联动（FE-LINK-506）
- AutoScroll 行为（FE-CHAT-106）
- 输入区（FE-CHAT-105）

## Dependencies

- FE-CHAT-103（数据源）、FE-THEME-002（token/字体约定）

## Input

- 架构文档第 5 节组件树、第 4 节排版约定

## Output

- chat/ 下三个组件 + lib 相对时间工具

## Business Rules

- 数值/时间戳用 mono 字体
- 消息一旦终态不再因流式更新重渲（selector 保证）
- 长文本自动折行，超长单词断词处理

## API Dependencies

- 无（只读 store）

## Data Dependencies

- chatSlice.messages

## Permission

- 同全局：无鉴权

## Error Handling

- content 为空的 pending ai 消息渲染为「思考中」占位，不出现空白气泡闪烁

## Acceptance Criteria

- Mock 全剧本下渲染正确：流式光标、终态三态样式、时间戳
- 长回复（>2000 字）流畅无明显卡顿
- 空会话引导文案可见

## Test Requirements

- 组件测试：三态消息渲染快照、流式追加更新断言
- 渲染次数计数测试：终态消息不被流式更新波及
