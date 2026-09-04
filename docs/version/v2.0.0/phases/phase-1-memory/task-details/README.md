# Phase 1 Task Details 索引

> 每个 Task 一份 Detail，与 [../tasks.md](../tasks.md) MEM-001~011 一一对应，无遗漏。所有 Detail 锚定真实代码路径，未与 architecture/design 冲突，未提前设计 Phase 2~6 能力。

| Task | Detail | Capability | 依赖 | 核心代码锚点 |
|---|---|---|---|---|
| MEM-001 | [MEM-001.md](MEM-001.md) | Foundation | 无 | core/db.py Memory ORM、migrations/versions 0021→0022、core/settings.py |
| MEM-002 | [MEM-002.md](MEM-002.md) | Core/Ingest | MEM-001 | application/post_process.py run_memory_extract/STEP_HANDLERS、memory_service.extract_and_save |
| MEM-003 | [MEM-003.md](MEM-003.md) | Core/Evaluator | MEM-002 | memory_policy.apply_policy、memory_conflict.same_topic、memory_repository.create_memory、core/llm_factory.py |
| MEM-004 | [MEM-004.md](MEM-004.md) | Core/Embedding | MEM-001, 003 | llm_factory、memory_repository（新函数）、settings llm_profiles |
| MEM-005 | [MEM-005.md](MEM-005.md) | Core/Lifecycle | MEM-001, 003 | memory_service.reclaim/_execute_forget、memory_repository.supersede/touch、memory_conflict |
| MEM-006 | [MEM-006.md](MEM-006.md) | Integration/Retriever | MEM-004, 005 | context_builder.py L38、memory_service.retrieve/_score_memory、memory_repository.list_active |
| MEM-007 | [MEM-007.md](MEM-007.md) | Integration/Commands | MEM-005 | memory_service._execute_forget、memory_conflict.same_topic、settings action_memory_policy_json |
| MEM-008 | [MEM-008.md](MEM-008.md) | Observability | MEM-003/005/006 | trace_collector.py、api/v1/debug.py、application/observability.py |
| MEM-009 | [MEM-009.md](MEM-009.md) | Infra | MEM-001, 005 | main.py lifespan 5 循环、memory_service.run_memory_reclaim_loop |
| MEM-010 | [MEM-010.md](MEM-010.md) | Evaluation | MEM-006, 008 | services/offline_evaluator.py、evaluation_engine、evaluation_judge_chain |
| MEM-011 | [MEM-011.md](MEM-011.md) | Integration | MEM-006 | context_builder、prompts/builder._fit_variable_parts、summary_service、settings memory_recent_context_messages |
