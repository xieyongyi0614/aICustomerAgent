# V8.5 M6：Memory Integration（关系记忆）

> 明确边界：什么进关系账本、什么进长期记忆、什么两者都进。"用户喜欢咖啡"是 V4 的记忆；"用户曾在低谷时向我袒露压力"是关系记忆——后者由 V8.5 主动投递进 V4 既有仓储。

## 1. 路由边界表（核心交付）

| 来源 | relationship_events 账本 | memories 长期记忆 | milestones | conflicts |
|---|---|---|---|---|
| 普通互动信号（未升格） | ✗（证据窗内存） | ✗ | — | — |
| 升格关系事件 | ✓ | 仅 memory_worthy 类（§3） | — | — |
| 里程碑 | ✗（独立表） | memory_worthy=true 者 ✓ | ✓ | — |
| 冲突爆发 / 和解 | 结算行走 source=system | ✓ | — | ✓ |
| 疏远检测 / 张力消退 | source=system ✓ | ✗（系统性小事不入记忆） | — | — |
| 记忆回放补记（V5 既有） | ✓（打折） | ✗（它本身就是记忆） | ✗ | ✗ |
| 用户偏好/事实（"喜欢咖啡"） | ✗ | ✓（走 V4 既有第 5 步提取，与 V8.5 无关） | — | — |

原则：**账本记"对关系有影响的事"（全量、含负向、含琐碎），记忆记"角色该长期记住的事"（高显著、以正向与转折为主）**——两表查询模式不同（审计流水 vs 对话素材），不合并（V5 与 emotion_history 分表的同款论证）。

## 2. 投递机制（素材投递模式，同 V8 memory_bridge）

```text
to_memory_candidates(outcome, milestones, conflicts) -> list[MemoryCandidate]   # 纯函数
  → 投递既有 memory 仓储（save 语义），同用户写锁内
  → 不改 memory_service / extractor / memory_extract 第 5 步（零侵入）
```

- `MemoryCandidate`：content（模板渲染，§4）、type=relationship_event、source=relationship_evolution、importance（§3 映射）、character_id="asuna"。
- 投递失败不回滚演化（架构.md 降级矩阵）；重复投递防御：同 cause 24h 内去重（复用 V5 replay 的 cause 去重模式）。

## 3. memory_worthy 清单与 importance 映射

| 来源 | importance |
|---|---|
| 里程碑（memory_worthy） | 0.90 |
| 和解（resolved=reconciled） | 0.85 |
| strong self_disclosure | 0.80 |
| conflict / boundary_violation 爆发 | 0.75 |
| promise_kept / promise_broken | 0.80 |

- 全部 ≥ V4 既有 importance 阈值 0.6（无过滤风险）；V4 检索的 type affinity 对 relationship_event 天然亲和，检索侧零新机制。
- 负向记忆照投（"我们也吵过架"）——角色记得冲突才谈得上修复与原谅。

## 4. 内容模板（确定性渲染，不用 LLM）

`relationship_lexicon.py` 资产模板，第一人称角色视角：

| 事件 | 模板（示例） |
|---|---|
| first_self_disclosure | TA 第一次向我敞开心扉，说起了{cause}。 |
| first_support_in_distress | 我最低落的时候，是 TA 陪着我。 |
| conflict | 我们争吵过，为了{cause}。 |
| 和解 | 我们和好了。经过那次争吵，我更珍惜现在的相处。 |
| promise_broken | TA 曾答应我的事没有做到。 |

- cause 截断 20 字防敏感信息直入记忆；模板是人格资产（可按角色定制），不是通用文案。

## 5. 与 V4/V5 既有机制的分工

| 机制 | 归属 | V8.5 动作 |
|---|---|---|
| memory_extract（第 5 步，LLM 抽取偏好/事实/事件） | V4 既有 | 不动；两条通道并存，主题天然分流（关系记忆带模板标记， extractor 少抽到也不损失） |
| relationship_event type 记忆召回 → 补记账本 | V5 既有（replay_discount=0.5） | 不动；不产信号不进证据窗 |
| 事件记忆登记 scheduled_followup | V6 既有 | 不动 |

## 6. 验收标准

- 边界表逐格断言（正反例矩阵）。
- 投递内容/类型/importance/source 正确；24h 去重生效。
- 模板渲染确定性（同输入同输出）、cause 截断生效。
- memory_extract / 检索 / replay 既有测试零回归（零侵入验证）。
- 投递异常注入：演化与账本不受影响。
