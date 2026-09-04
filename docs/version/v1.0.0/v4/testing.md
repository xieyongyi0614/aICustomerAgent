# Testing

## 1. 约定

沿用现有约定：pytest + pytest-asyncio、FakeLLM（`set_llm` 注入）、单元测试内存 SQLite、HTTP/e2e 连 PostgreSQL。测试禁止真实 LLM。

> 2026-08-29 测试瘦身：原聚合文件 `tests/e2e/test_memory_matrix.py` 已删除，10 项矩阵的断言由细粒度文件承载（`tests/integration/test_memory.py`、`test_memory_retrieval.py`、`test_memory_e2e.py` 等），覆盖面无损失。

## 2. 测试矩阵（10 项必测）

| # | Case | 层 | 断言 |
|---|---|---|---|
| 1 | 用户偏好提取 | extractor+policy | "我从来不喝咖啡" → user_preference candidate，user_stated，save 成功 |
| 2 | 用户事实提取 | extractor+policy | "我家猫三岁了" → user_fact，save 成功 |
| 3 | 普通闲聊不保存 | policy | "今天天气不错" → 0 candidate 或全部被丢弃；库无新增 |
| 4 | AI 猜测不保存 | policy | AI 回复"你一定很开心" → ai_inferred candidate 被 R1 丢弃 |
| 5 | Memory Retrieval | retriever | 字面相关 / 高 importance / 近期记忆正确排序；无关输入返回空或兜底；失效记忆不返回 |
| 6 | Memory Conflict | conflict | "喜欢咖啡"→"不喝咖啡了"：旧 superseded/invalidate，仅一条 active，无矛盾 |
| 7 | 用户要求删除 | extractor+privacy | "别记住这件事" → suppress 零写入；"忘了吧" → 硬删除 |
| 8 | 用户修改旧记忆 | conflict | "我现在改成喜欢喝茶了" → 旧 superseded，新 active |
| 9 | Memory 不阻塞 SSE | e2e | extractor 抛异常/超时 → token 流完整、done 事件正常、首 token 时延不变 |
| 10 | V2/V3 全部回归 | 全量 | `uv run pytest tests/ -v` 全绿（含 V3 scene 测试） |

## 3. 附加单测

- `test_memory_models.py`：MemoryCandidate 校验（target_memory_id 联动、类型/阈值越界）。
- `test_memory_policy.py`：R1~R8 每条规则正反例。
- `test_memory_conflict.py`：update/supersede/invalidate 三分支 + 阈值边界 + 同轮矛盾对丢弃。
- `test_memory_repository.py`：扩展表 CRUD、status 过滤、last_accessed_at 回写、迁移映射。
- `test_memory_context.py`：注入条数/字符预算、去重、无记忆兼容。
- `test_memory_e2e.py`：FakeLLM 两轮跨会话：第一轮存"用户不喝咖啡"，新 session 第二轮召回并出现在 Prompt。

## 4. 真实模型回归（上线前人工）

- 跨 3 个会话的偏好记忆自然引用。
- 冲突更新后角色不再提旧偏好。
- "不要记住这件事"生效。
- 记忆不导致角色抢话/罗列记忆（context 规则约束生效）。

## 5. 验收标准

- 10 项必测全绿 + 附加单测全绿 + V2/V3 零回归。
- FakeLLM 无法验证语义质量的部分（ extractor 判定准确率）以真实回归记录为准。
