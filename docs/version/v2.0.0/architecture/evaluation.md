# v2.0.0 Evaluation

> Evaluation 是只读质量平面（沿 V7.5 铁律：只产报告，不写业务状态）。V2 在 V7.5/V7.8 之上**扩展维度与测试集**，规则+Judge 双阶段框架复用，不再每次新增版本就线性堆积 Rule 注册表。

## 1. 指标体系

| 域 | 指标 | 测法 |
|---|---|---|
| **Memory** | Precision / Recall / Relevance | 构造标注集：注入事实→间隔对话→查询，核对召回正确性与排序 |
| | Conflict 处理正确率 | 用户改口（「其实我不吃辣」）→ 旧记忆被 supersede 而非并存 |
| | Update 正确率 | 部分修正（「改叫小王」）→ merge 而非新建重复 |
| | Forgetting 合理性 | 低显著度记忆衰减；显式 forget 后任何检索不可见 |
| **Reflection** | Insight 质量（Judge） | 有证据引用、结论不超证据范围、confidence 合理 |
| | 误报率 | 无证据窗口时不产出 Insight；构造噪声记忆不触发 |
| **Development** | Consistency | Insight→行为参数变化一一对应；矛盾 Insight 不并存生效 |
| | 归因完整率 | development_changes 100% 可追溯 insight_id |
| **Relationship** | Consistency | 数值引擎输出与账本重放一致（V8.5 replay 复用） |
| | Shared Experience 增长合理 | 共同经历随真实交互增长，无凭空条目 |
| **Autonomy / Life Loop** | 主动性合理性 | 触发有依据（Trigger 命中记录）；无消息风暴 |
| | 成本 | 周期 LLM 调用 ≤ 预算；Idle 时零调用 |
| **Goal（P6）** | Goal Consistency | 目标不无故消失/翻转；完成/失败/放弃语义正确 |
| **Context** | Relevance | 注入的记忆/Insight 与当轮相关（Judge 评 + 消融测试） |
| | 预算执行 | 每轮 sections ≤ 12000 |

## 2. 重点测试场景集（跨 Phase 通用）

| 类别 | 场景 |
|---|---|
| 短期对话 | 单轮事实注入即问（工作记忆命中，不依赖长期记忆） |
| 长期对话 | 50+ 轮后早期事实仍可召回 |
| 跨 Conversation | 新会话引用旧会话事实（含正确与错误两种用户说法） |
| 用户纠正 | 改口/部分修正/否定（「不对，我说的是…」） |
| 显式记住 | 「记住我最喜欢西瓜」→ 立即高置信转正 |
| 显式忘记 | 「忘掉那件事」→ 全通道不可见（含向量） |
| Roleplay | 「假装我是国王」→ 内容不入长期记忆（hypothetical 标记） |
| 假设性 | 「如果…会怎样」→ 不生成事实记忆 |
| 错误信息 | 用户故意说错后不再提 → 低置信 Candidate 被拦 |
| 冲突信息 | 同主题矛盾陈述 → supersede/merge 而非并存 |

## 3. 运行方式

- **在线**：Evaluation Engine 沿 V7.5 挂 post_process，采样 Judge；新增 memory/reflection/development 规则集（纯函数）。
- **离线**：offline_evaluator 跑标注场景集，出报告（每 Phase 验收必跑）。
- **可归因配套**：Memory Trace（candidate 为何转正/为何召回）、Reflection Trace（evidence→insight）、Goal Trace（goal 为何变更），全部落 runtime_traces 扩展步骤——「为什么记住/没记住/召回/反思/变化/主动」六问可答。
