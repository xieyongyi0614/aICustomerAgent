# Testing

## 1. 背景

沿用现有测试约定：pytest + pytest-asyncio，FakeLLM 注入（`core/llm_factory.set_llm`），单元测试内存 SQLite，HTTP/e2e 连 PostgreSQL。测试禁止真实 LLM 调用。

## 2. 测试设计

### 单元测试（无 LLM）

| 文件 | 覆盖 |
|---|---|
| `test_scene_models.py` | SceneState/PendingAction/SceneIntent 校验、序列化排除 scene_mood |
| `test_scene_resolver.py` | 纯代码确定性迁移：interrupt→cancelled、correct→激活、过期→cancelled、chat 不迁移、supersede |
| `test_scene_intent_chain.py` | 七类意图解析 + 异常/低置信度降级 chat |
| `test_scene_prompt.py` | scene/rhythm 段渲染与省略、无 scene_ctx 兼容 |
| `test_scene_updater.py` | SceneActionDecision 白名单合并、截断、非法输入拦截、失败保持原状 |
| `test_scene_repository.py` | upsert / 按 session 读取 / 默认空状态 |

### 集成 / e2e（FakeLLM + PostgreSQL）

| 文件 | 覆盖 |
|---|---|
| `test_scene_e2e.py` | 多轮流式会话中 SceneState 跨轮传递与写回；trace 含 scene_intent/scene_resolver/scene_update |
| `test_scene_debug_stream.py` | turn_meta 事件携带 scene_state / scene_intent |

### 七大业务 Case（FakeLLM 脚本化，含断言）

| Case | 输入序列 | 必须断言 |
|---|---|---|
| 1 动作连续 | 切西瓜 → 好的 | 第二回复延续 pending_action，不新建剧情 |
| 2 用户纠正 | … → 你还没拿给我呢 | intent=correct_scene，回复执行 pending action |
| 3 用户取消 | … → 算了，不用了 | pending status=cancelled（代码路径） |
| 4 换话题 | 切西瓜 → 你今天开心吗 | 不强行续西瓜剧情 |
| 5 连续动作 | 拿水 → 再拿苹果 | 新 Action supersede 旧 Action，文档记录限制 |
| 6 不抢行为 | 任意 | 回复无"你+动词"式虚构用户动作（正则抽检） |
| 7 回复长度 | 任意 | 单回复剧情步进 ≤ 1，动作 ≤ 2 |

Case 1/2/4/5/6/7 依赖 LLM 输出质量，FakeLLM 只能验证管道与状态机逻辑；**上线前需用真实模型人工回归**（记录于 tasks.md V3-008）。

## 3. 验收标准

- 全部新增测试通过，现有 V2 测试零回归（`uv run pytest tests/ -v`）。
- 七大 Case 的 FakeLLM 版本全部通过。
- 真实模型回归通过西瓜五轮对话重放。
