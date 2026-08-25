# FE-CHAT-103 · useChat 会话闭环 Hook 与 chat store

## Task ID

FE-CHAT-103

## Task Name

useChat Hook 与 Zustand chat/session store（send / stream / stop / error / session 回填）

## Type

FE

## Priority

P0

## Description

实现聊天主闭环的状态层与编排层：Zustand store（messages、streaming 态、sessionId、connectionStatus、AbortController 持有）+ useChat Hook（send/stop 动作）。Hook 是唯一允许触发传输并写 store 的层。

## Scope

- `stores/chatSlice`：消息数组（id/role/content/status）、当前 streaming 消息指针、connectionStatus 流转
- `stores/sessionSlice`：当前 sessionId、apiMode、「无 session 待创建」语义
- AbortController 由 store 持有（非 React state），stop() 触发 abort 并把进行中消息标 stopped
- `hooks/useChat.ts`：send(content)——组装请求经 transport 工厂发送；onEvent 分派：delta 增量追加至流式消息、turn_meta 写入 debug 相关 store 位（Overview 消费，字段先落 store）、done 回填 sessionId（首响应用 X-Session-Id 头或 done 体）/记录 turn_id、error 将当前消息置 error 态并保存错误信息
- 发送前本地先插入 human 消息与 pending 态 ai 占位消息（id 前端生成）
- connectionStatus 随请求生命周期流转 connecting→open→closed/error

## Out of Scope

- 消息渲染样式（FE-CHAT-104）、输入交互（105）、Retry/Clear（507）
- turn_meta 的可视化（301）
- REST 类数据

## Dependencies

- API-FE-101（开发依赖）；FE-MOCK-102（验收依赖）
- **并行标记**：与 BE-TURNMETA-201 并行开发；真实联调在汇合点 I1 完成（本任务验收以 Mock 为准，I1 通过后补一次真机回归）

## Input

- 架构文档第 7 节（状态管理分工）、第 8.1 节契约、第 6 节 ChatMessage/TurnAnalysis 模型

## Output

- chatSlice / sessionSlice / useChat
- store 单测可独立运行

## Business Rules

- 流式高频更新只允许触发订阅了对应 selector 的组件重渲（store 切片粒度约束）
- 一轮未结束禁止并发发起下一轮 send（输入侧禁用在 105 实施，store 层同样防御：streaming 中 send 直接拒绝）
- stopped 与 error 是两种终态：abort→stopped；error 事件/网络失败→error 且保留已收到的部分文本
- sessionId 优先级：本地已有 > 响应头 X-Session-Id > done 行字段

## API Dependencies

- POST /api/v1/chat/message（经 transport 抽象）

## Data Dependencies

- 无持久化（刷新即失，属调试工具预期行为）

## Permission

- 同全局：无鉴权

## Error Handling

- onError：消息置 error 态、connectionStatus=error、错误详情存入消息对象（渲染层展示）
- transport 层已吞掉的行级错误不再上抛；store 层只处理事件级错误

## Acceptance Criteria

- Mock 剧本全流程：发送→增量渲染数据就绪→完成终态正确
- Stop 后消息为 stopped 且后续 delta 不再入 store
- 错误剧本产生 error 终态且保留半截文本
- 新会话首轮完成后 sessionId 已回填并可被 TopBar 读取

## Test Requirements

- store/hook 单测（renderHook + 注入 MockTransport）：四条核心链路（正常/中止/错误/会话回填）各一用例
- selector 粒度冒烟：流式更新不触碰无关切片
