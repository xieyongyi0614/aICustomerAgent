# Memory Update

## 1. 背景

V1 的 `extract_and_save` 已在 `_post_process` 后台执行，满足"不阻塞 SSE"；但内部是单条决策直写库，无 Candidate/Policy/Conflict 分层。

## 2. 目标管线

```text
User Message + AI Response
   ↓（后台任务，与 state_update / summary 并行，互相独立容错）
Memory Extractor（LLM）
   ↓ list[MemoryCandidate]
Memory Policy（纯代码硬规则）
   ↓ 通过过滤的 candidates
Memory Conflict Resolver（纯代码，查库比对）
   ↓ save / update / supersede / invalidate 指令
Memory Repository（扩展 memories 表）
```

## 3. 执行时机与容错

- 挂载点：`agent_service._post_process`（回答已完整产出并落库后启动）。
- 每段独立 try/except + trace（`memory_extract` / `memory_policy` / `memory_conflict`），任一段失败只影响记忆，不影响回答。
- 提取失败不重试（防重复入库）；写库失败记日志。
- 顺序：extract → policy → conflict → repository，单条 candidate 独立处理，一条失败不影响其他条。

## 4. 写入规则

- save：新建行，status=active，写入 source/confidence/importance/character_id。
- update：更新目标行 content/importance/updated_at（同义改良，见 memory-conflict.md）。
- supersede：旧行 status=superseded + superseded_by=新行 id，新行 status=active。
- invalidate：旧行 status=invalidated（用户否定旧信息）。
- forget：硬删除（用户明确要求，见 privacy.md）。
- 召回侧写回：仅更新 last_accessed_at（低优先级异步，失败可容忍）。

## 5. 与 V3 的边界

- Memory 写入绝不触碰 SceneState / PendingAction。
- V3 的 `scene_state_updater` 与 V4 的 memory 管线并行运行，互不依赖（仅共享 trace collector）。

## 6. 验收标准

- SSE 首 token 时延与 V3 版本相比无可测量差异（记忆全在后台）。
- 管线各段失败注入测试：回答照常产出。
- save/update/supersede/invalidate/forget 五种写入结果各有一条单测。
