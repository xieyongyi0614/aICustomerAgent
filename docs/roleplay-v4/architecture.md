# V4 Architecture

## 1. 现状分析（V1/V2/V3 已有能力）

V1 已有基础记忆系统：

| 组件 | 现状 | V4 处理 |
|---|---|---|
| `core/db.py Memory` 表 | id/user_id/memory/memory_type/importance/created_at/updated_at | **扩展字段**：character_id、content(source 重命名)、confidence、source、status、last_accessed_at、expires_at |
| `models/memory.py MemoryDecision` | should_save/memory/memory_type/importance | **升级为 MemoryCandidate**：+confidence/source/action |
| `chains/extractor_chain.py` | 单次 LLM 提取 | 复用，Prompt 重写（V4 类型 + 隐私指令识别） |
| `services/memory_service.py extract_and_save` | 提取→阈值→exists_similar→落库 | **拆分为 Candidate→Policy→Conflict→Repository 四段** |
| `memory_service.retrieve` | 字符级 tokenize 重叠打分 | **重写为加权结构化召回** |
| `context_builder.build` | retrieve → ConversationState.memories | 保留接口，注入逻辑升级（memory-context.md） |
| `agent_service._post_process` | 后台执行记忆提取 | 保留（已满足"不阻塞 SSE"） |
| `api/v1/history.py`、Debug MemoryPanel | 记忆列表 UI | 扩展展示 status/source |

V3 提供：`scene_state` 持久化范式、trace step 模式、后台任务容错模式 —— V4 全部沿用。

## 2. 目标架构

```text
User Message + AI Response
        │（回答结束后，后台任务）
        ▼
Memory Extractor（LLM，复用 structured_chain）
        │
        ▼
MemoryCandidate(type/content/importance/confidence/source/action)
        │
        ▼
Memory Policy（纯代码：硬规则过滤）
  ├─ source=ai_inferred → discard
  ├─ importance/confidence 低于阈值 → discard
  ├─ action=forget → 隐私处理（privacy.md）
  └─ action=suppress → 本轮禁止保存
        │
        ▼
Memory Conflict Resolver（纯代码）
  ├─ 与现有记忆高度相似 → update / supersede
  └─ 显式否定 → invalidate 旧记忆
        │
        ▼
Memory Repository（扩展 memories 表）
        │
── 下一轮对话开始 ──
        ▼
Memory Retriever（结构化加权召回，无向量）
        │
        ▼
Memory Context（排序/去重/截断）→ ConversationState.memories → PromptBuilder memory 段
```

## 3. 与 V2/V3 职责边界

- V2：CharacterState/RelationshipState（角色内在）——**不受 V4 影响**。
- V3：SceneState/PendingAction（现在/刚才）——**不受 V4 影响**；Memory 不得参与 Scene 迁移。
- V4：跨会话长期事实（过去）——只读注入 Prompt，只写在后台。

## 4. 边界情况

- Extractor 失败/超时：跳过本轮记忆，不影响回答（沿用 V1 容错模式）。
- Retriever 失败：memories 为空列表，回答照常。
- 记忆表迁移：Alembic 增量迁移，旧数据按映射规则迁移（memory-model.md）。

## 5. 验收标准

- V1 既有记忆测试迁移后全部通过；V2/V3 全量回归零破坏。
- trace 新增 `memory_extract` / `memory_policy` / `memory_conflict` step。
- 10 项测试（testing.md）全部通过。
