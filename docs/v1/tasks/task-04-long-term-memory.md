# Task 4 — 长期记忆提取 + 存储 + 检索

> 从聊天中提取值得长期保存的信息，存入 memories 表，后续对话按需召回。
> 核心：只保存有价值信息（"今天吃了拉面"不保存，"我喜欢寿司"保存）。
> 架构参考：`docs/v1/v1-architecture.md` §8 Task 4

## 目标

- Memory Extractor 用 Pydantic Structured Output 判断是否保存
- 长期记忆落库（SQLite memories 表）
- 每次用户输入时检索相关记忆注入 Prompt
- 接口为未来 Vector DB 预留

## 涉及文件

| 操作 | 文件 |
|---|---|
| 新建 | `app/models/memory.py`（MemoryDecision / UserMemory / MemoryType） |
| 新建 | `app/chains/extractor_chain.py` |
| 新建 | `app/prompts/extractor.py` |
| 新建 | `app/repositories/memory_repository.py` |
| 新建 | `app/services/memory_service.py` |
| 修改 | `app/core/db.py`（增加 memories 表） |
| 修改 | `app/prompts/builder.py`、`app/services/context_builder.py`、`app/services/agent_service.py` |

## 实现步骤

1. `core/db.py`：增加 `memories` 表（id / user_id / memory / memory_type / importance / created_at / updated_at，`idx_memories_user` 索引）。
2. `models/memory.py`：

   ```python
   class MemoryDecision(BaseModel):
       should_save: bool
       memory: str | None
       memory_type: Literal["preference", "fact", "goal", "experience", "relationship"]
       importance: float
   ```

3. `prompts/extractor.py`：提示词给出各类型定义 + "不值得保存"的负例（日常流水账不保存）。
4. `chains/extractor_chain.py`：`ChatPromptTemplate | llm.with_structured_output(MemoryDecision)`，输入用户消息 + AI 回复。
5. `repositories/memory_repository.py`：`create_memory`、`list_by_user(user_id)`、`exists_similar(memory)` 去重检查。
6. `services/memory_service.py`：
   - `extract_and_save(user_id, user_input, ai_reply)`：调 extractor_chain → `should_save and importance >= 0.6` → 去重 → 入库
   - `retrieve(user_id, user_input, top_k=5)`：V1 用关键词匹配（词重叠度打分，返回 top-K 且分数 ≥ 阈值）。**接口签名对齐未来向量检索**，V2 只换实现不动调用方。
7. `prompts/builder.py`：注入 User Memory 段（列出用户长期信息）。
8. `agent_service.py`：流结束后调用 `memory_service.extract_and_save`。

## 验收标准

- "我喜欢日本料理，尤其是寿司" → 保存为 `preference`
- "今天吃了拉面" → `should_save=false`，不落库
- "我正在开发 AI Agent 项目" → 保存为 `goal`
- 后续问"我想吃点什么"能检索出寿司偏好并体现在回答中
- 相同信息重复出现不产生重复记忆（去重生效）
- `retrieve()` 接口不依赖具体存储实现，可整体替换为向量检索