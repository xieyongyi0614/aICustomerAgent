# Scene Intent Router

## 1. 背景

V2 `RoleMode.intent`（technical/casual/emotional/roleplay/sao_lore）表达的是**表现风格意图**，用于选模式；没有表达**剧情控制意图**。

## 2. 问题

`好的`、`你还没拿给我呢`、`算了不用了` 这类消息对剧情的指令性语义完全没有被捕获。

## 3. SceneIntent 分类（V3 第一版固定 7 类）

```python
class SceneIntent(str, Enum):
    chat = "chat"                          # 一般聊天："你好""随便聊聊"
    request_action = "request_action"      # 要求角色做某事："给我拿瓶水"
    continue_scene = "continue_scene"      # 无新任务，继续当前场景："好的"/"嗯"/"然后呢？"
    correct_scene = "correct_scene"        # 指出状态错误："你还没拿给我呢"
    interrupt = "interrupt"                # 中断当前行为："算了，不用了"
    question = "question"                  # 询问角色："你今天怎么了？"
    emotional = "emotional"                # 表达情绪："我有点累"
```

说明：`question` 与 `emotional` 对剧情控制而言同样是"不产生状态迁移"的软意图（与 chat 同属一类迁移），保留它们是为了 Debug 可观测性与后续扩展（V4/V5 情绪/关系系统），但**不新增状态迁移路径**。

## 4. 设计

- 独立 `scene_intent_chain`（structured output → `SceneIntentResult(intent, confidence, reason)`），与 `role_router` 并行调用。
- **与 RoleMode 的关系**：SceneIntent 只供场景控制，不改变 mode 选择；二者输出都在 turn_meta 中暴露。
- 降级策略与 V2 一致：异常/非法输出/低置信度（阈值复用 `router_confidence_threshold`，或新增 `scene_intent_threshold` 于 settings.py）→ 降级为 `chat`。
- `chat` 意味着"不触碰场景状态迁移逻辑"，是最安全的默认值。
- 模型 / Prompt / 文档三处必须使用同一份 7 类定义（单一来源 `app/models/scene.py`）。

## 5. 边界情况

- 消息同时含多意图（"算了不切了，陪我聊聊天"）→ 优先级：interrupt > correct_scene > request_action > continue_scene > chat（要求 LLM 输出单一主意图，prompt 中说明优先级）。
- correct_scene 与 interrupt 语义相近：correct = "事情没做完/状态错了，去做"；interrupt = "不要做了"。

## 6. 验收标准

- 单测覆盖七类意图各至少 2 条样例 + 降级路径。
- 与 role_router 并行，总时延不高于现有 role_router 单独时延 + 20%。
