# Character Agent Debug Console 前端开发任务注册表（01-task-registry）

> 输入来源：`docs/version/v1.0.0/frontend/frontend-architecture.md`（Debug Console 前端架构设计，含三项已确认决策 D-F1/D-F2/D-F3）
> 输出用途：可直接交给 Coding Agent 逐 Task 执行。
> 本文件为前端工程唯一任务入口，`tasks/` 目录下每个文件对应一个 Task。
> 断点状态（2026-08-25）：全部任务待开始（pending）。

---

## 1. 任务拆分原则

一个 Task 必须满足：

- 只有一个明确目标
- 可以独立开发、独立测试、独立验收
- 有明确输入 / 输出 / 依赖

**禁止**出现「完成 Debug 面板」「完成聊天功能」这类过大粒度任务。

## 2. 任务类型（Type）

| 类型 | 含义 |
|---|---|
| ARCH | 工程 / 架构基建（脚手架、布局壳、部署方案） |
| FE | 前端业务组件 / Hook / Store |
| BE | 后端改动（FastAPI 侧，遵守 `apps/backend/AGENTS.md`） |
| API | 接口层（前端 API Client 或后端 HTTP 端点） |
| DB | 数据访问 / 存储（本批次无：trace 默认内存存储，不动 Alembic） |
| TEST | 测试场景 / 测试基座 |

## 3. 任务层级

```
Module（模块）
 ↓
Feature（功能点）
 ↓
Task（Task ID，见下表；详情见 tasks/ 各文件）
 ↓
Subtask（见各 Task 文件内 Scope 条目，每条可独立验证）
```

## 4. 模块 / Feature / Task 结构总览

### 模块一：工程基建（Foundation）

| Feature | Task ID | Task 名称 | Type | 优先级 | 状态 |
|---|---|---|---|---|---|
| 脚手架 | ARCH-FE-001 | 前端工程脚手架与工程约定 | ARCH | P0 | pending |
| 设计系统 | FE-THEME-002 | 设计 Token、暗色主题与 shadcn 基础组件 | FE | P0 | pending |
| 布局壳 | FE-LAYOUT-003 | Workbench 双栏布局与响应式阶梯 | FE | P0 | pending |
| 全局控制 | FE-TOPBAR-004 | TopBar（session 管理 / 连接状态 / Mock 开关） | FE | P0 | pending |

### 模块二：聊天通道（Chat Pipeline）

| Feature | Task ID | Task 名称 | Type | 优先级 | 状态 |
|---|---|---|---|---|---|
| 传输层 | API-FE-101 | ChatStreamTransport 抽象与 NDJSON 事件归一化 | API | P0 | pending |
| Mock 流 | FE-MOCK-102 | Mock 流传输与剧本库（含 real/mock 工厂切换） | FE | P0 | pending |
| 会话闭环 | FE-CHAT-103 | useChat Hook 与 chat store（send/stream/stop/error/session 回填） | FE | P0 | pending |
| 消息渲染 | FE-CHAT-104 | MessageList / MessageItem / StreamingText | FE | P0 | pending |
| 输入栏 | FE-CHAT-105 | 输入栏 Send / Stop 交互 | FE | P0 | pending |
| 滚动控制 | FE-CHAT-106 | AutoScroll 跟随与上滚暂停 | FE | P0 | pending |
| 即时观测 | FE-OVERVIEW-301 | Overview 面板最小版（消费 turn_meta）＋ DebugTabs 骨架 | FE | P0 | pending |

### 模块三：后端协作（Backend Lane，可与前端全程并行）

| Feature | Task ID | Task 名称 | Type | 优先级 | 状态 |
|---|---|---|---|---|---|
| 流契约 | BE-TURNMETA-201 | turn_meta 行下发与 done 行附 turn_id | BE | P0 | pending |
| Trace 采集 | BE-TRACE-401 | Agent Trace 步骤采集器（编排埋点） | BE | P1 | pending |
| 观测端点 | BE-API-402 | GET /api/v1/state（状态 + emotion_history） | API | P1 | pending |
| 观测端点 | BE-API-403 | 历史消息端点 ＋ 记忆列表端点 | API | P1 | pending |
| 观测端点 | BE-API-404 | GET /api/v1/debug/turns/{turn_id}/trace | API | P1 | pending |

### 模块四：Debug 数据通道与面板（Observability UI）

| Feature | Task ID | Task 名称 | Type | 优先级 | 状态 |
|---|---|---|---|---|---|
| 数据通道 | API-FE-501 | REST Client、TanStack Query 集成与有界轮询策略 | API | P1 | pending |
| 基础组件 | FE-JSON-502 | 自研 JsonViewer 折叠树 | FE | P1 | pending |
| State 面板 | FE-STATE-503 | StatePanel（角色状态卡 / 关系卡 / 情绪历史条） | FE | P1 | pending |
| Memory 面板 | FE-MEMORY-504 | MemoryPanel（命中/全量切换 ＋ Extractor 决策卡） | FE | P1 | pending |
| Trace 面板 | FE-TRACE-505 | TraceWaterfall 时间轴与步骤详情 | FE | P1 | pending |
| 联动 | FE-LINK-506 | TurnBadge 消息↔Trace 联动 ＋ RawPanel | FE | P1 | pending |
| 会话操作 | FE-ACTION-507 | Retry 重发与 Clear Conversation | FE | P1 | pending |

### 模块五：打磨与交付（Polish & Delivery）

| Feature | Task ID | Task 名称 | Type | 优先级 | 状态 |
|---|---|---|---|---|---|
| Mock 场景 | TEST-SCENE-601 | MSW 场景剧场完善（降级 / 错误 / 边界 fixtures） | TEST | P2 | pending |
| 打磨 | FE-POLISH-602 | 全局空态/错误态统一与性能评估 | FE | P2 | pending |
| 部署 | OPS-DEPLOY-603 | 生产构建与 FastAPI StaticFiles 挂载方案 | ARCH | P2 | pending |

## 5. 总体依赖 DAG

```
ARCH-FE-001（脚手架，唯一无依赖任务）
 │
 ├─→ FE-THEME-002 ─→ FE-LAYOUT-003 ─┬→ FE-TOPBAR-004（另需 FE-CHAT-103）
 │                                  └→ 各面板容器位（OVERVIEW/STATE/MEMORY/TRACE/RAW 挂载点）
 │
 └─→ API-FE-101（传输抽象＋事件归一化）
      ├─→ FE-MOCK-102（剧本库＋real/mock 工厂）
      │    └─→ FE-CHAT-103（先用 Mock 验收）
      │         ├─→ FE-CHAT-104 ─→ FE-CHAT-106
      │         ├─→ FE-CHAT-105
      │         ├─→ FE-ACTION-507
      │         ├─→ FE-OVERVIEW-301（消费 turn_meta；缺失时降级提示）
      │         └─→ FE-TOPBAR-004
      │
      └─（事件契约）→ API-FE-501（REST＋Query＋有界轮询）
           ├─→ FE-STATE-503 ─┐
           ├─→ FE-MEMORY-504 ┤（均还需 FE-THEME-002、FE-JSON-502）
           └─→ FE-TRACE-505 ─┴→ FE-LINK-506（另需 FE-CHAT-103/104 的 selectedTurnId 与消息渲染）

后端泳道（互相独立、与前端并行）：
BE-TURNMETA-201（无前置，基于 V2 现状）
BE-TRACE-401（无前置）──→ BE-API-404（另需 BE-TURNMETA-201 的 turn_id 定位约定）
BE-API-402（无前置，读 V2 既有三表）
BE-API-403（无前置，读 V1 既有表）

打磨链：
{FE-MOCK-102 + API-FE-501} → TEST-SCENE-601 → FE-POLISH-602
{全部 P0 + P1 完成} → OPS-DEPLOY-603
```

### 集成汇合点（前后端联调节点）

| 汇合点 | 参与任务 | 联调内容 |
|---|---|---|
| I1 | FE-CHAT-103 × BE-TURNMETA-201 | 真实流联调：turn_meta 解析渲染、done 行 turn_id 回填、旧契约兼容回归（curl 忽略新行） |
| I2 | API-FE-501 × BE-API-402/403/404 | 真实 REST 联调：字段对齐、pending→complete 有界轮询、超时兜底 |

两条泳道在各自汇合点之前完全并行，互不阻塞。

### 并行化建议（双泳道）

- **泳道 A（前端主线）**：`ARCH-FE-001 → {FE-THEME-002、API-FE-101} → FE-LAYOUT-003 / FE-MOCK-102 → FE-CHAT-103 → 渲染与交互组`
- **泳道 B（后端观测线）**：`BE-TURNMETA-201` 先行（P0）；随后 `BE-TRACE-401 → BE-API-404`，`BE-API-402 / BE-API-403` 随时可插空
- 泳道 A 不等泳道 B：一切以 Mock 验收，汇合点处做一次集成验收即可。

## 6. 优先级说明

| 优先级 | 定义 | 范围 |
|---|---|---|
| **P0** | 前端 MVP（Phase 1）必须完成 | ARCH-FE-001 ~ FE-OVERVIEW-301、BE-TURNMETA-201 |
| **P1** | 可观察性完整版（Phase 2）重要项 | BE-TRACE-401、BE-API-402~404、API-FE-501、FE-JSON-502~FE-ACTION-507 |
| **P2** | 后续版本（Phase 3） | TEST-SCENE-601、FE-POLISH-602、OPS-DEPLOY-603 |

## 7. 执行顺序建议（按队列）

```
队列 1（可并行）：ARCH-FE-001 ‖ BE-TURNMETA-201 ‖ BE-TRACE-401 ‖ BE-API-402 ‖ BE-API-403
队列 2（可并行）：FE-THEME-002、API-FE-101、BE-API-404
队列 3（可并行）：FE-LAYOUT-003、FE-MOCK-102
队列 4：FE-CHAT-103（Mock 验收 → 汇合点 I1 真实联调）、API-FE-501、FE-JSON-502
队列 5（可并行）：FE-CHAT-104、FE-CHAT-105、FE-OVERVIEW-301、FE-TOPBAR-004、
                 FE-STATE-503、FE-MEMORY-504、FE-TRACE-505
队列 6（可并行）：FE-CHAT-106、FE-ACTION-507、FE-LINK-506（汇合点 I2 随 501 验收）
队列 7：TEST-SCENE-601 → FE-POLISH-602 → OPS-DEPLOY-603
```

## 8. 工程约束提醒

### 前端（apps/frontend，新建）

- 目录职责红线：`components/` 禁止出现 fetch；`api/` 不认识 React；`stores/` 只存状态不发起请求（动作由 hooks 编排）；`types/backend`（Pydantic 镜像，全可选）与 `types/domain` 分离。
- `mocks/` 只允许被 `api/index.ts` 工厂 import；fixtures 必须通过 domain 类型校验。
- real/mock 切换唯一分支点是 `api/index.ts` 工厂，由 `VITE_API_MODE` 控制。
- 不添加代码注释，用命名表达意图；禁止硬编码密钥（本工具无需密钥，baseURL 走 env）。
- 组件库只用 Tailwind + shadcn/ui；JSON Viewer 自研，不引第三方大件。

### 后端（apps/backend，改动须遵守既有 AGENTS.md）

- 依赖方向单向 `api → services → repositories → core`；测试禁止真实 LLM（FakeLLM 注入）；HTTP/e2e 集成测试连 PostgreSQL。
- turn_meta 属增量行（带 `type` 字段），不得破坏现行 delta/done/detail 契约。
- trace 采集为旁路观测：埋点失败 try/except 隔离，不影响主流程与人格稳定性；默认内存存储，不建表、不走 Alembic。
- 新增常量（如 trace 容量上限）进 `core/settings.py`，禁止硬编码。
- 只有用户明确要求时才提交 / 推送 / 建 PR。

## 9. 目录结构

```
docs/version/v1.0.0/frontend/
├── 01-task-registry.md              # 本注册表（唯一任务入口）
├── frontend-architecture.md         # 架构设计（任务输入依据）
└── tasks/
    ├── ARCH-FE-001-scaffold.md
    ├── FE-THEME-002-design-tokens.md
    ├── FE-LAYOUT-003-workbench.md
    ├── FE-TOPBAR-004-topbar.md
    ├── API-FE-101-stream-transport.md
    ├── FE-MOCK-102-mock-stream.md
    ├── FE-CHAT-103-use-chat.md
    ├── FE-CHAT-104-message-list.md
    ├── FE-CHAT-105-input-bar.md
    ├── FE-CHAT-106-auto-scroll.md
    ├── FE-OVERVIEW-301-overview.md
    ├── BE-TURNMETA-201-turn-meta.md
    ├── BE-TRACE-401-trace-collector.md
    ├── BE-API-402-state-endpoint.md
    ├── BE-API-403-history-endpoints.md
    ├── BE-API-404-turn-trace-endpoint.md
    ├── API-FE-501-rest-query.md
    ├── FE-JSON-502-json-viewer.md
    ├── FE-STATE-503-state-panel.md
    ├── FE-MEMORY-504-memory-panel.md
    ├── FE-TRACE-505-trace-panel.md
    ├── FE-LINK-506-badge-linkage.md
    ├── FE-ACTION-507-retry-clear.md
    ├── TEST-SCENE-601-msw-scenes.md
    ├── FE-POLISH-602-polish.md
    └── OPS-DEPLOY-603-deploy.md
```
