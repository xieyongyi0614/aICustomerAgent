# Roleplay V4 任务注册表

> 开发入口。按依赖顺序执行；P0 = V4 必须，P1 = 推荐，P2 = 延期。
> 策略：一次只执行一个 Task，完成后运行测试、展示改动，再进入下一个。

## Task 列表

### V4-001 Memory 数据模型（P0）

- **目标**：MemoryCandidate / MemoryExtraction / UserMemoryV4 模型。
- **前置**：无。
- **涉及文件**：`app/models/memory.py`（扩展，保留 V1 类型别名过渡）。
- **实现内容**：MemoryType 4 类、MemorySource、MemoryAction、Candidate（action/source/confidence/target 联动校验）。
- **验收标准**：模型校验、非法值拒绝。
- **测试要求**：`tests/test_memory_models.py`。Priority: P0

### V4-002 memories 表扩展 + 迁移（P0）

- **目标**：memories 表加列（character_id/confidence/source/status/superseded_by/last_accessed_at/expires_at）+ 旧类型映射迁移。
- **前置**：V4-001。
- **涉及文件**：`app/core/db.py`、`migrations/`、`app/repositories/memory_repository.py`。
- **实现内容**：Alembic 增量迁移；repository 增加按 (user, character, status) 查询、update/supersede/invalidate/forget 操作。
- **验收标准**：迁移与 ORM 一致；旧数据映射正确。
- **测试要求**：`tests/test_memory_repository.py`、迁移一致性测试。Priority: P0

### V4-003 Memory Extractor 升级（P0）

- **目标**：输出 0~3 条 MemoryCandidate，含 source 判定与隐私指令识别。
- **前置**：V4-001。
- **涉及文件**：`app/chains/extractor_chain.py`、`app/prompts/extractor.py`、`app/core/settings.py`（memory_max_candidates 等）。
- **实现内容**：MemoryExtraction 结构化输出；Prompt 重写（4 类正反例、去语境化、suppress/forget/invalidate 指令）。
- **验收标准**：候选上限强制；ai_inferred 正确标注；隐私指令可识别。
- **测试要求**：`tests/test_memory_extractor.py`（FakeLLM）。Priority: P0

### V4-004 Memory Policy（P0）

- **目标**：纯代码保存过滤（R1~R8）。
- **前置**：V4-001。
- **涉及文件**：`app/services/memory_policy.py`（新增）。
- **实现内容**：8 条硬规则按序执行，输出 保存/丢弃/转隐私 三种结果。
- **验收标准**：AI 猜测/闲聊/低置信零入库。
- **测试要求**：`tests/test_memory_policy.py`。Priority: P0

### V4-005 Memory Conflict Resolver（P0）

- **目标**：update/supersede/invalidate 冲突处理。
- **前置**：V4-002、V4-004。
- **涉及文件**：`app/services/memory_conflict.py`（新增）、`app/core/settings.py`（conflict 阈值）。
- **实现内容**：同主题匹配（分词 jaccard）+ relation 判定执行。
- **验收标准**：咖啡冲突场景仅剩一条 active 记忆。
- **测试要求**：`tests/test_memory_conflict.py`。Priority: P0

### V4-006 Memory Retriever 重写（P0）

- **目标**：加权结构化召回替代字符重叠。
- **前置**：V4-002。
- **涉及文件**：`app/services/memory_service.py`（retrieve 重写）、`app/core/settings.py`（memory_top_k/memory_min_score）。
- **实现内容**：0.45/0.25/0.20/0.10 四因子打分 + status 过滤 + last_accessed_at 回写。
- **验收标准**：失效记忆不召回；排序符合预期。
- **测试要求**：`tests/test_memory_retrieval.py`。Priority: P0

### V4-007 Memory Context 注入（P0）

- **目标**：Prompt 注入预算/去重/格式。
- **前置**：V4-006。
- **涉及文件**：`app/services/context_builder.py`、`app/prompts/builder.py`、`app/models/conversation.py`（memories 类型升级）。
- **实现内容**：5 条/400 字预算、去重、memory 段渲染、空记忆兼容。
- **验收标准**：V1 无记忆路径输出不变；上限强制。
- **测试要求**：`tests/test_memory_context.py`。Priority: P0

### V4-008 编排接入 + 隐私执行（P0）

- **目标**：新管线接入 `_post_process`；suppress/forget 强制执行。
- **前置**：V4-003、V4-005。
- **涉及文件**：`app/services/memory_service.py`（extract_and_save 重构为四段管线）、`app/services/agent_service.py`、`app/services/trace_collector.py`。
- **实现内容**：extract→policy→conflict→repository 串联，各段独立容错 + trace step。
- **验收标准**：Case 9（不阻塞 SSE）；隐私 Case 7/8 通过。
- **测试要求**：`tests/test_memory_update_flow.py`、`tests/test_memory_e2e.py`。Priority: P0

### V4-009 十项必测 + 全量回归（P0）

- **目标**：testing.md 测试矩阵全绿。
- **前置**：V4-008。
- **涉及文件**：`tests/`（补充聚合用例）。
- **实现内容**：Case 1~10；整理真实模型回归清单。
- **验收标准**：全量 `uv run pytest tests/ -v` 通过，V2/V3 零回归。
- **测试要求**：同左。Priority: P0

### V4-010 Debug/API 扩展（P1）

- **目标**：记忆列表展示 status/source/confidence + 变更历史。
- **前置**：V4-008。
- **涉及文件**：`app/api/v1/history.py`、`app/api/v1/schemas.py`、前端 MemoryPanel。
- **实现内容**：API 返回 status 等新字段；前端面板展示 active/superseded 分组。
- **验收标准**：面板可见记忆生命周期。
- **测试要求**：API 单测 + 前端 Vitest。Priority: P1

### V4-011 过期回收后台任务（P2）

- **目标**：expires_at 定期批量 invalidated。
- **前置**：V4-002。
- **涉及文件**：`app/services/memory_service.py`、启动钩子。
- **验收标准**：过期记忆 24h 内失效。
- **测试要求**：单测时间注入。Priority: P2

### V4-012 隐私分级与总量治理（P2，仅文档）

- **目标**：敏感信息分级保存策略 + 200 条软上限治理方案。
- **验收标准**：结论文档化。Priority: P2

## 依赖图

```text
V4-001 → V4-002 → V4-005 ↘
   │        ↘ V4-006 → V4-007 → V4-008 → V4-009 → V4-010
   └→ V4-003 ↗          V4-011（独立）    ↘ 真实回归
V4-012（仅文档）
```
