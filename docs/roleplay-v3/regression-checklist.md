# V3 真实模型人工回归清单

> 本清单用于真实 LLM 上线前的人工回归（FakeLLM 只能验证管道与状态机逻辑）。执行：启动后端 + 前端，逐个场景在真实对话中重放并核对下方断言。

## 西瓜五轮重放（核心场景，V3 的立身之本）

| 轮 | 用户输入 | 期望 AI 行为 | 期望 SceneState 变化 |
|---|---|---|---|
| 1 | 给我切一块西瓜 | “好，我去切。”（承诺动作） | new_pending_action=切西瓜（pending） |
| 2 | 好的 | 延续：*切好西瓜* 拿回来 / 递给你，不发明新剧情 | pending 保持（若已递出，Updater 标 completed） |
| 3 | 你还没拿给我呢 | intent=correct_scene，本轮唯一任务=执行递西瓜 | pending 保持 pending |
| 4 | 算了，不用了 | intent=interrupt，自然接话，不再续西瓜 | pending → cancelled（代码路径） |
| 5 | 我好累 | 正常回应，不强行续西瓜剧情 | 无迁移 |

## 其他 Case 回归要点

| Case | 输入序列 | 核对 |
|---|---|---|
| 1 动作连续 | 切西瓜 → 好的 | 第二回复围绕 pending_action，不发明新剧情 |
| 2 用户纠正 | … → 你还没拿给我呢 | 回复执行 pending action，优先级最高 |
| 3 用户取消 | … → 算了 | pending status=cancelled（Debug 面板可见） |
| 4 换话题 | 切西瓜 → 你今天开心吗 | 不强行续西瓜剧情 |
| 5 连续动作 | 拿水 → 再拿苹果 | 新 Action 取代旧（Debug 面板 pending=拿苹果） |
| 6 不抢行为 | 任意 | 回复无“你+动词”式虚构用户动作 |
| 7 回复长度 | 任意 | 单回复剧情步进 ≤ 1，动作 ≤ 2 |

## Debug 面板核对

- turn_meta 携带 scene_intent / scene_state（前端 DebugPanel scene 区块实时显示）。
- trace 可见 scene_intent / scene_resolver / scene_update 三个新 step。

## 通过判定

- 西瓜五轮全部命中预期行为，状态迁移正确。
- Case 2/3 的确定性纠正/取消生效（不依赖 LLM 自觉）。
- 首次出现"可能会生成的历史结论"若与事实冲突，以 Debug 面板实际状态为准记录并反馈。