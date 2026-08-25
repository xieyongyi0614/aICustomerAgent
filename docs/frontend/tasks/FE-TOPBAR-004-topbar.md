# FE-TOPBAR-004 · TopBar 全局控制

## Task ID

FE-TOPBAR-004

## Task Name

TopBar：session 管理、连接状态灯与 Mock/Real 开关

## Type

FE

## Priority

P0

## Description

实现全局顶栏：当前 session 展示与新建/切换、后端连接状态指示灯、Mock|Real 模式开关。它是架构文档「信息架构修正点 1」的全局关切承载区。

## Scope

- 当前 sessionId 显示（mono 字体、可复制）与会话下拉列表（历史会话来自后续 REST 任务，本阶段允许仅显示当前会话 + 「+New」；下拉列表结构预留）
- 「+ New Session」动作：清空本地会话状态，下一次发送自动创建新会话（与 FE-CHAT-103 的 sessionSlice 对接）
- 连接状态灯：connecting / open(绿) / closed(灰) / error(红)，数据源为 chat store 的 connectionStatus
- Mock|Real 开关：读取运行时 apiMode；切换时弹出确认提示「需要刷新页面生效」，确认后写入 localStorage 偏好并 reload（工厂在启动时按 env + 本地覆盖决定模式）
- 设置 Dialog 入口占位（内容 Phase 3 再填充，允许空态）

## Out of Scope

- 历史会话列表的真实数据加载（依赖 BE-API-403 + API-FE-501，届时补接下拉）
- 鉴权 / 用户身份

## Dependencies

- FE-LAYOUT-003（挂载位）、FE-CHAT-103（session/connection 状态源）

## Input

- `docs/frontend/frontend-architecture.md` 第 3 节（信息架构）、第 8 节（apiMode 工厂约定）

## Output

- TopBar 组件 + 与 chat store 的双向接线（读状态、发 new-session 动作）

## Business Rules

- Mock 开关是显式行为：必须经确认再 reload，禁止静默切换导致用户误以为在测真实后端
- apiMode 在界面上始终可见（开关态即标识），防止调试者混淆数据来源
- sessionId 一律 mono 呈现并提供复制按钮

## API Dependencies

- 无直接调用；间接消费 FE-CHAT-103 的连接状态

## Data Dependencies

- chat store（sessionSlice）：sessionId、connectionStatus、apiMode

## Permission

- 同全局：无鉴权

## Error Handling

- connectionStatus 为 error 时状态灯红色并附 tooltip 提示检查后端；TopBar 自身不发起网络请求，不新增错误路径

## Acceptance Criteria

- 新建会话后旧消息清空、下次发送产生新 sessionId 并回显
- 断开后端进程状态灯变红，恢复后变绿
- Mock↔Real 切换经确认后 reload 且模式生效（界面可辨）

## Test Requirements

- 组件交互测试：新建会话、开关确认流、状态灯四态渲染
