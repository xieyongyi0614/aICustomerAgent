# Pending Action

## 1. 背景

AI 说"我去切西瓜"之后，没有任何机制记录这件事还没完成。

## 2. 问题

- 用户说"好的"，AI 重新发明剧情而不是递西瓜。
- 用户纠正"你还没拿给我呢"，AI 无法优先修正。

## 3. 目标

单一主 PendingAction + **代码驱动的确定性生命周期**。

## 4. 生命周期（谁在什么情况下改状态）

| 事件 | 触发者 | 迁移 |
|---|---|---|
| 创建（new_pending_action） | Updater（LLM 判定）+ 代码白名单合并 | 旧 pending → `superseded`，新 action → `pending` |
| 完成（pending_action_done） | Updater（LLM 判定，如 AI 回复已包含递出动作） | `pending` → `completed` |
| 取消 | **Resolver 代码**，SceneIntent=interrupt 时强制 | `pending` → `cancelled` |
| 纠正 | **Resolver 代码**，SceneIntent=correct_scene 时强制 | `pending` 保持 `pending`，并在 Prompt 注入"必须先执行该动作"指令段 |
| 过期 | **Resolver 代码**：pending 存活超过 N 轮（settings，默认 5）未被完成/取消 | `pending` → `cancelled`（防僵尸） |
| 话题切换 | Resolver 代码，SceneIntent=chat 且连续 2 轮未提及动作时 | 不强杀，仅不再注入"必须执行"指令段 |

设计原则：**cancel / correct / 过期全部由代码执行，不信任 LLM 自觉**。LLM 只负责"创建"与"完成"两种需要语义判断的迁移。

## 5. 多 Action 问题（Case 5）

- 第一版**只保留一个主 PendingAction**：新 request_action 到来时旧 Action 置 `superseded`。
- 理由：Action Queue 引入排序、冲突、逐个完成跟踪，收益低风险高；实际对话中"拿水+拿苹果"通常会被合并成一个复合动作（"拿水和苹果"），由 Updater 创建时合并。
- 若后续证明 superseded 丢失有效任务，再评估 Queue（已在 tasks.md 中列为 P2 文档任务）。

## 6. 边界情况

- AI 声称做了动作但用户纠正：correct_scene 分支直接重新激活执行，不判断"是否真的做了"。
- pending_action 在回答前已被 Resolver 处理（如 interrupt），同一轮 Updater 不得复活它（白名单合并只允许引用 Resolver 输出的最新状态）。

## 7. 验收标准

- Case 2：correct_scene → 回复执行 pending action（不新建剧情）。
- Case 3：interrupt → status=cancelled（代码路径，可用纯单测验证，无需 LLM）。
- Case 4：切话题不强行续剧情。
- Case 5：第二个请求 supersede 第一个。
