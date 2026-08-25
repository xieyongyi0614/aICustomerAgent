# FE-MOCK-102 · Mock 流传输与剧本库（含 real/mock 工厂切换）

## Task ID

FE-MOCK-102

## Task Name

MockChatStreamTransport、剧本库与 api/index.ts 工厂切换

## Type

FE

## Priority

P0

## Description

实现与 Real 版同签名的 Mock 流传输：按「剧本」逐行发射 turn_meta → delta×N → done（或 error），延迟参数化以模拟真实 LLM 时序；并落地 real/mock 唯一切换点。Phase 1 的全部前端验收都以本任务提供的 Mock 运行。

## Scope

- `mocks/stream-scripts.ts`：剧本数据（非代码逻辑的纯数据 fixtures），至少 5 条：
  1. 日常闲聊（default 模式、neutral/daily/normal_reply）
  2. 用户诉苦（immersive、sad/setback→comfort）
  3. 用户报喜（immersive、excited/achievement→celebrate）
  4. LLM 错误流（中途 error 事件收尾）
  5. 旧契约兼容流（无 turn_meta，仅 delta/done——用于验证降级路径）
- 剧本匹配规则：按用户输入关键词命中剧本，未命中走默认剧本
- `mocks/MockChatStreamTransport`：实现 ChatStreamTransport 接口；逐事件按可配置延迟发射；支持 signal 中止；模拟 X-Session-Id 回填语义（生成 mock sessionId）
- `api/index.ts` 工厂：启动时读取 env `VITE_API_MODE` + localStorage 覆盖（见 FE-TOPBAR-004），导出对应 Transport 实现；此文件是 mocks/ 唯一允许被引用的边界之外唯一入口（工厂本身）

## Out of Scope

- MSW REST handlers（API-FE-501 内落基座、TEST-SCENE-601 完善）
- 真实后端联调（汇合点 I1）

## Dependencies

- API-FE-101（接口与事件类型定稿）

## Input

- 架构文档第 9 节（Mock Architecture）、第 8.1 节事件契约、附录 A1

## Output

- 可通过 VITE_API_MODE=mock 全链路运行的流式 Mock
- 剧本库（后续 TEST-SCENE-601 扩充）

## Business Rules

- mocks/ 目录只允许被 `api/index.ts` import，任何组件/Hook 禁止直接引用
- 剧本数据必须满足 domain 类型校验（类型错误在编译期暴露）——mock 是类型契约的第一个消费者
- Mock 的 turn_meta 内容必须使用合法枚举值，且降级剧本需体现默认值组合供 Overview 降级徽章演示

## API Dependencies

- 无网络调用；接口签名对齐 ChatStreamTransport

## Data Dependencies

- 无持久化

## Permission

- 同全局：无鉴权

## Error Handling

- 错误剧本按契约发 error 事件后正常关闭，不得抛出未捕获异常
- signal 中止立即停止发射

## Acceptance Criteria

- `VITE_API_MODE=mock` 下：5 条剧本均可触发并产出正确事件序列（含时序间隔）
- 切回 real 后 Mock 代码零参与（工厂分支验证）
- 剧本 5 在前端表现为「turn_meta 缺失」的降级展示路径

## Test Requirements

- 每条剧本一个单测：断言完整事件序列与顺序
- 工厂单测：两种 mode 下返回的实现类型正确
