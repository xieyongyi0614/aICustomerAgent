# V1 开发任务注册表（01-task-registry）

> 输入来源：`docs/v1/v1-architecture.md`（三层架构设计）
> 输出用途：可直接交给 Coding Agent 逐 Task 执行。
> 本文件为唯一任务入口，`tasks/` 目录下每个文件对应一个 Task。

---

## 1. 任务拆分原则

一个 Task 必须满足：

- 只有一个明确目标
- 可以独立开发
- 可以独立测试
- 可以独立验收
- 有明确输入 / 输出
- 有明确依赖关系

**禁止**出现"完成记忆系统""完成后台"这类过大粒度任务。

## 2. 任务类型（Type）

| 类型 | 含义 |
|---|---|
| ARCH | 架构 / 工程结构 |
| BE | 后端业务逻辑（模型、服务、链、编排） |
| API | API 端点 / 请求响应 |
| DB | 数据访问 / 存储 |
| TEST | 测试 |

> 注：本项目 V1 为纯后端（FastAPI），无前端模块，故不含 FE 类型任务。

## 3. 任务层级

```
Module（模块）
 ↓
Feature（功能点）
 ↓
Task（Task ID，见下表）
 ↓
Subtask（见各 Task 文件内"Subtask 拆分"）
```

---

## 4. 模块 / Feature / Task 结构总览

### 模块一：基础设施（Infrastructure）

| Feature | Task ID | Task 名称 | 优先级 |
|---|---|---|---|
| 工程骨架 | ARCH-01 | 三层目录落地与旧模块迁移 | P0 |
| 数据库 | DB-01 | SQLite 引擎与 ORM 建表 | P0 |
| 配置 | BE-01 | 环境配置模块（pydantic-settings） | P0 |
| LLM | BE-02 | LLM 单例工厂 | P0 |

### 模块二：模型与资产（Models & Assets）

| Feature | Task ID | Task 名称 | 优先级 |
|---|---|---|---|
| 数据模型 | BE-03 | Pydantic 数据模型定义 | P0 |
| 角色资产 | BE-04 | 角色资产模块（character/） | P0 |
| 提示词 | BE-05 | Prompt 模板与 PromptBuilder | P0 |

### 模块三：数据访问层（Repositories）

| Feature | Task ID | Task 名称 | 优先级 |
|---|---|---|---|
| 会话仓储 | DB-02 | conversation_repository | P0 |
| 摘要仓储 | DB-03 | summary_repository | P0 |
| 记忆仓储 | DB-04 | memory_repository | P0 |

### 模块四：业务服务（Services & Chains）

| Feature | Task ID | Task 名称 | 优先级 |
|---|---|---|---|
| 路由链 | BE-06 | role_router_chain | P0 |
| 短期记忆 | BE-07 | conversation_service（多轮窗口） | P0 |
| 对话摘要 | BE-08 | summary_chain 与 summary_service | P0 |
| 记忆提取链 | BE-09 | extractor_chain | P0 |
| 长期记忆 | BE-10 | memory_service（提取落库 + 检索） | P0 |
| 上下文组装 | BE-11 | context_builder | P0 |
| 回答链 | BE-12 | answer_chain | P0 |
| 主编排 | BE-13 | agent_service（核心对话流程） | P0 |
| 路由降级 | BE-14 | 路由低置信度降级 | P1 |

### 模块五：API 表现层（API）

| Feature | Task ID | Task 名称 | 优先级 |
|---|---|---|---|
| 聊天端点 | API-01 | chat 端点（流式响应 + 错误处理） | P0 |

### 模块六：测试（Testing）

| Feature | Task ID | Task 名称 | 优先级 |
|---|---|---|---|
| 测试基座 | TEST-01 | 测试基础设施（conftest） | P0 |
| 核心单测 | TEST-02 | 核心单元测试 | P0 |
| 摘要专项 | TEST-03 | 摘要专项测试 | P0 |
| 端到端 | TEST-04 | 端到端集成测试 | P0 |

---

## 5. 总体依赖 DAG

```
ARCH-01（工程骨架）
 │
 ├─→ DB-01（建表）─→ DB-02（conversation_repo）─→ BE-07（短期记忆）
 │        │             └───────────────────────────→ 含 Summary 触发位
 │        ├─→ DB-03（summary_repo）─→ BE-08（摘要链+服务）
 │        └─→ DB-04（memory_repo）─→ BE-10（长期记忆服务）
 │
 ├─→ BE-01（配置）─→ BE-02（LLM 工厂）
 │
 ├─→ BE-03（Pydantic 模型）
 │
 └─→ BE-04（角色资产）─→ BE-05（Prompt 模板+Builder）

BE-02 + BE-03 + BE-05 ─→ BE-06（路由链）
BE-02 + BE-03 + BE-05 ─→ BE-09（提取链）
BE-02 + BE-05 ──────────→ BE-12（回答链）
BE-03 ─────────────────→ BE-11（Context Builder）
BE-03 + BE-07 ─────────→ BE-08 输入依赖
BE-09 + BE-04 ─────────→ BE-10 输入依赖

BE-06 + BE-07 + BE-08 + BE-10 + BE-11 + BE-12 ─→ BE-13（主编排）
BE-13 ─→ API-01（chat 端点）

BE-06 ─→ BE-14（P1 路由降级，可后置）

TEST-01（conftest）→ TEST-02 / TEST-03 / TEST-04
```

### 并行化建议

以下分支可**并行开发**（不互相阻塞）：

- 分支 A：`DB-01 → DB-02 → BE-07`
- 分支 B：`BE-01 → BE-02` + `BE-03` + `BE-04 → BE-05`
- 分支 C：`DB-01 → DB-04` + `BE-09`（BE-10 汇合）
- 分支 D：`DB-01 → DB-03` + `BE-07`（BE-08 汇合）

`BE-13`（编排）与 `API-01` 必须等所有 P0 前置完成后再开始，属收敛节点。

---

## 6. MVP 优先级说明

| 优先级 | 定义 | 范围 |
|---|---|---|
| **P0** | MVP 必须完成 | 架构、配置、LLM 工厂、建表、全部模型/资产、全部仓储、路由链、短期记忆、摘要、长期记忆、Context Builder、回答链、主编排、chat 端点、测试基座、核心单测、摘要单测、端到端测试 |
| **P1** | 重要，可在核心流程完成后开发 | 路由低置信度降级（BE-14） |
| **P2** | 后续版本 | 见下方 backlog |

### P2 未来版本 Backlog（暂不拆分 Task）

- 长期记忆检索升级为向量检索（Embedding 相似度，替换关键词匹配）
- 记忆管理 API（查看 / 编辑 / 删除长期记忆）
- 多用户鉴权与用户级记忆隔离
- 摘要多版本历史与可追溯性
- 流式响应心跳 / 断线重连

---

## 7. 执行顺序建议（按队列）

```
队列 1（P0，可并行）：ARCH-01 → {DB-01, BE-01, BE-03, BE-04}
队列 2（P0）：{DB-01→DB-02→BE-07}, {BE-01→BE-02}, {BE-03+BE-04→BE-05},
              {DB-01→DB-04}
队列 3（P0）：{BE-06, BE-09, BE-12}, {DB-03}, {BE-10, BE-11}
队列 4（P0）：{BE-08}, {BE-13}
队列 5（P0）：API-01
队列 6（P0）：TEST-01 → TEST-02 → TEST-03 → TEST-04
队列 7（P1）：BE-14（可与测试并行）
```

---

## 8. 目录结构

```
docs/v1/
├── 01-task-registry.md      # 本注册表（唯一入口）
├── v1-architecture.md       # 架构总设计（任务输入依据）
├── README.md                # V1 索引
└── tasks/
    ├── ARCH-01-scaffold.md
    ├── DB-01-database-init.md
    ├── DB-02-conversation-repo.md
    ├── DB-03-summary-repo.md
    ├── DB-04-memory-repo.md
    ├── BE-01-settings.md
    ├── BE-02-llm-factory.md
    ├── BE-03-pydantic-models.md
    ├── BE-04-character-assets.md
    ├── BE-05-prompt-builder.md
    ├── BE-06-router-chain.md
    ├── BE-07-conversation-service.md
    ├── BE-08-summary-service.md
    ├── BE-09-extractor-chain.md
    ├── BE-10-memory-service.md
    ├── BE-11-context-builder.md
    ├── BE-12-answer-chain.md
    ├── BE-13-agent-service.md
    ├── BE-14-router-degradation.md
    ├── API-01-chat-endpoint.md
    ├── TEST-01-test-infra.md
    ├── TEST-02-core-unit-tests.md
    ├── TEST-03-summary-tests.md
    └── TEST-04-e2e-tests.md
```