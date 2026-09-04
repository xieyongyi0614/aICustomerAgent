# Roleplay V3：场景状态与行为连续性系统

> 状态：规划完成，待实现
> 前置：V2（角色状态系统，见 `docs/version/v1.0.0/v2/`）

## 一句话定义

让 AI 从「根据聊天记录生成角色回复」升级为「基于当前场景状态进行角色扮演」：AI 知道自己在哪里、正在做什么、上一件事做到哪一步、还有什么没完成，并根据用户意图自然推进或修正场景。

## 文档导航

| 文档 | 内容 |
|---|---|
| [architecture.md](architecture.md) | 整体架构、Runnable vs LangGraph 选型、职责边界 |
| [scene-state.md](scene-state.md) | SceneState 数据模型、持久/临时状态划分 |
| [intent-router.md](scene-intent-router.md) | SceneIntent 分类与路由设计 |
| [pending-action.md](pending-action.md) | PendingAction 生命周期与确定性迁移 |
| [state-update.md](state-update.md) | State Updater：确定性优先 + LLM 兜底 |
| [response-rhythm.md](response-rhythm.md) | 回复节奏控制与 RP 硬约束 |
| [prompt-design.md](prompt-design.md) | V3 Prompt 注入设计 |
| [testing.md](testing.md) | 七大 Case 测试设计 |
| [tasks.md](tasks.md) | 任务注册表（开发入口） |

## V2 / V3 职责边界

- **V2 负责**：角色是谁、什么性格、怎么说话、整体表现风格（professional/default/immersive）。
- **V3 负责**：现在在哪里、正在做什么、刚做了什么、什么没完成、用户现在想做什么、下一步怎么推进。

V3 不重新设计角色 Prompt，只新增 scene / rhythm 两个 Prompt 分节。

## 核心决策记录

1. **继续使用 LangChain Runnable**，不引入 LangGraph（理由见 architecture.md）。
2. **SceneIntent 与 RoleMode 分离**：RoleMode 管"怎么说话"，SceneIntent 管"剧情控制"。
3. **确定性状态迁移由代码处理**：interrupt / cancel / correct 不依赖 LLM 自觉。
4. **单一主 PendingAction**：新 Action supersede 旧 Action，Action Queue 延期（Case 5 限制见 pending-action.md）。
5. **不引入**：向量库、RAG、长期记忆、多 Agent、世界观系统。

## 验收标准（最终判据）

重放原始"西瓜"五轮对话：第 2 轮后每轮回复都与 pending_action 状态一致，且无一次替用户行动、无一次凭空创造用户心理。
