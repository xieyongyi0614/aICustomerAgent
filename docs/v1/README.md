# V1 角色对话 Agent

让「亚丝娜」从单轮问答升级为具备记忆能力的角色 Agent。

## 文档导航

| 文档 | 说明 |
|---|---|
| [01-task-registry.md](01-task-registry.md) | **任务注册表（唯一入口）**：DAG、优先级、并行队列 |
| [v1-architecture.md](v1-architecture.md) | 三层架构总设计（V0 问题、架构图、DB、Pydantic、Chain、LangGraph 复用） |
| [tasks/](tasks/) | 25 个可执行 Task 文件（见下方清单） |

## 任务清单

### 基础设施（P0）

| Task ID | 文件 | 名称 |
|---|---|---|
| ARCH-01 | [tasks/ARCH-01-scaffold.md](tasks/ARCH-01-scaffold.md) | 三层目录落地与旧模块迁移 |
| DB-01 | [tasks/DB-01-database-init.md](tasks/DB-01-database-init.md) | SQLite 引擎与 ORM 建表 |
| BE-01 | [tasks/BE-01-settings.md](tasks/BE-01-settings.md) | 环境配置模块 |
| BE-02 | [tasks/BE-02-llm-factory.md](tasks/BE-02-llm-factory.md) | LLM 单例工厂 |

### 模型与资产（P0）

| Task ID | 文件 | 名称 |
|---|---|---|
| BE-03 | [tasks/BE-03-pydantic-models.md](tasks/BE-03-pydantic-models.md) | Pydantic 数据模型 |
| BE-04 | [tasks/BE-04-character-assets.md](tasks/BE-04-character-assets.md) | 角色资产模块 |
| BE-05 | [tasks/BE-05-prompt-builder.md](tasks/BE-05-prompt-builder.md) | Prompt 模板与 PromptBuilder |

### 数据访问层（P0）

| Task ID | 文件 | 名称 |
|---|---|---|
| DB-02 | [tasks/DB-02-conversation-repo.md](tasks/DB-02-conversation-repo.md) | conversation_repository |
| DB-03 | [tasks/DB-03-summary-repo.md](tasks/DB-03-summary-repo.md) | summary_repository |
| DB-04 | [tasks/DB-04-memory-repo.md](tasks/DB-04-memory-repo.md) | memory_repository |

### 业务服务（P0 / P1）

| Task ID | 文件 | 名称 | 优先级 |
|---|---|---|---|
| BE-06 | [tasks/BE-06-router-chain.md](tasks/BE-06-router-chain.md) | role_router_chain | P0 |
| BE-07 | [tasks/BE-07-conversation-service.md](tasks/BE-07-conversation-service.md) | conversation_service（短期记忆） | P0 |
| BE-08 | [tasks/BE-08-summary-service.md](tasks/BE-08-summary-service.md) | summary_chain 与 summary_service | P0 |
| BE-09 | [tasks/BE-09-extractor-chain.md](tasks/BE-09-extractor-chain.md) | extractor_chain | P0 |
| BE-10 | [tasks/BE-10-memory-service.md](tasks/BE-10-memory-service.md) | memory_service（长期记忆） | P0 |
| BE-11 | [tasks/BE-11-context-builder.md](tasks/BE-11-context-builder.md) | context_builder | P0 |
| BE-12 | [tasks/BE-12-answer-chain.md](tasks/BE-12-answer-chain.md) | answer_chain | P0 |
| BE-13 | [tasks/BE-13-agent-service.md](tasks/BE-13-agent-service.md) | agent_service（主编排） | P0 |
| BE-14 | [tasks/BE-14-router-degradation.md](tasks/BE-14-router-degradation.md) | 路由低置信度降级 | P1 |

### API 表现层（P0）

| Task ID | 文件 | 名称 |
|---|---|---|
| API-01 | [tasks/API-01-chat-endpoint.md](tasks/API-01-chat-endpoint.md) | chat 端点（流式 + 错误处理） |

### 测试（P0）

| Task ID | 文件 | 名称 |
|---|---|---|
| TEST-01 | [tasks/TEST-01-test-infra.md](tasks/TEST-01-test-infra.md) | 测试基础设施 |
| TEST-02 | [tasks/TEST-02-core-unit-tests.md](tasks/TEST-02-core-unit-tests.md) | 核心单元测试 |
| TEST-03 | [tasks/TEST-03-summary-tests.md](tasks/TEST-03-summary-tests.md) | 摘要专项测试 |
| TEST-04 | [tasks/TEST-04-e2e-tests.md](tasks/TEST-04-e2e-tests.md) | 端到端集成测试 |

## 任务进度

> 以 [01-task-registry.md](01-task-registry.md) 为准，此处仅记录完成状态。

| Task ID | 名称 | 状态 |
|---|---|---|
| ARCH-01 | 三层目录落地 | ⬜ |
| DB-01 | SQLite 建表 | ⬜ |
| BE-01 | 环境配置 | ⬜ |
| BE-02 | LLM 工厂 | ⬜ |
| BE-03 | Pydantic 模型 | ⬜ |
| BE-04 | 角色资产 | ⬜ |
| BE-05 | Prompt Builder | ⬜ |
| DB-02 | conversation_repo | ⬜ |
| DB-03 | summary_repo | ⬜ |
| DB-04 | memory_repo | ⬜ |
| BE-06 | 路由链 | ⬜ |
| BE-07 | 短期记忆 | ⬜ |
| BE-08 | 摘要服务 | ⬜ |
| BE-09 | 提取链 | ⬜ |
| BE-10 | 长期记忆 | ⬜ |
| BE-11 | Context Builder | ⬜ |
| BE-12 | 回答链 | ⬜ |
| BE-13 | 主编排 | ⬜ |
| API-01 | chat 端点 | ⬜ |
| TEST-01 | 测试基座 | ⬜ |
| TEST-02 | 核心单测 | ⬜ |
| TEST-03 | 摘要单测 | ⬜ |
| TEST-04 | 端到端 | ⬜ |
| BE-14 | 路由降级 (P1) | ⬜ |

## 目录约定

```
docs/v1/
├── 01-task-registry.md        # 任务注册表（唯一入口，含 DAG 与并行队列）
├── v1-architecture.md         # 架构总设计（任务输入依据）
├── README.md                  # 本索引
└── tasks/                     # 24 个可执行 Task 文件
```

> 依赖关系与并行策略见 [01-task-registry.md](01-task-registry.md) §5。