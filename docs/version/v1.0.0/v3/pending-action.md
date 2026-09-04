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

## 附录：Action Queue 评估（V3-010，默认不实现）

### A.1 评估问题

单主 PendingAction + supersede 会丢弃被取代的任务。需要基于真实使用数据判断丢失率是否高到值得引入 Queue。

### A.2 观测指标（上线后采集）

| 指标 | 定义 | 采集方式 |
|---|---|---|
| supersede 丢失率 | 被 supersede 的 action 中，用户后续再次提起的比例 | Debug 面板 / trace 记录 supersede 事件与后续 N 轮消息匹配 |
| 复合请求占比 | 单条消息同时请求 ≥ 2 个动作的比例 | SceneIntent=request_action 消息人工抽样 |
| 正常完成率 | pending 在过期/取消前被 completed 的比例 | scene_state trace 统计 |
| 误 supersede 投诉 | 用户反馈"我让它拿水它忘了"类问题的频次 | 人工回归记录 |

### A.3 判定标准

- supersede 丢失率 < 10% 且复合请求占比 < 15% → **维持单主 PendingAction**（当前默认）。
- 丢失率 ≥ 10% 或出现明确的用户可感知遗忘 → 再评估 Queue / 复合动作合并优化。

### A.4 结论（V3 第一版）

**不引入 Action Queue**。理由：

1. 真实对话中"拿水+拿苹果"通常被 Updater 合并为一个复合动作，Queue 收益低。
2. Queue 引入排序、冲突、逐个完成跟踪，复杂度与出错面显著上升。
3. 上述指标尚未有真实数据支撑，任何 Queue 设计在数据到位前都是猜测。

若后续数据触发 A.3 阈值，先考虑"复合动作合并"优化，其次才是 Queue。
