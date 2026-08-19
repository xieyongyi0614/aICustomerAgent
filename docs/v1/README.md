# V1 角色对话 Agent

让「亚丝娜」从单轮问答升级为具备记忆能力的角色 Agent。

## 文档导航

| 文档 | 说明 |
|---|---|
| [v1-architecture.md](v1-architecture.md) | 三层架构总设计（V0 问题、架构图、DB、Pydantic、Chain、LangGraph 复用） |
| [tasks/task-01-infrastructure.md](tasks/task-01-infrastructure.md) | 基础设施重构 |
| [tasks/task-02-short-term-memory.md](tasks/task-02-short-term-memory.md) | 短期记忆（多轮上下文） |
| [tasks/task-03-conversation-summary.md](tasks/task-03-conversation-summary.md) | 对话摘要 |
| [tasks/task-04-long-term-memory.md](tasks/task-04-long-term-memory.md) | 长期记忆提取/存储/检索 |
| [tasks/task-05-orchestration.md](tasks/task-05-orchestration.md) | 完整编排 + 端到端 |
| [tasks/task-06-testing.md](tasks/task-06-testing.md) | 测试 |

## 任务进度

| Task | 目标 | 状态 |
|---|---|---|
| Task 1 | 基础设施重构 | ⬜ |
| Task 2 | 短期记忆 | ⬜ |
| Task 3 | 对话摘要 | ⬜ |
| Task 4 | 长期记忆 | ⬜ |
| Task 5 | 完整编排 | ⬜ |
| Task 6 | 测试 | ⬜ |

## 目录约定

```
docs/v1/
├── v1-architecture.md        # 架构总设计
├── README.md                 # 本索引
└── tasks/                    # 任务拆分（按开发顺序）
    ├── task-01-infrastructure.md
    ├── task-02-short-term-memory.md
    ├── task-03-conversation-summary.md
    ├── task-04-long-term-memory.md
    ├── task-05-orchestration.md
    └── task-06-testing.md
```

> 依赖顺序：1 → 2 → 3 → 4 → 5 → 6。Task 5 依赖前四个全部完成。