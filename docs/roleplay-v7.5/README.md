# Roleplay V7.5：Character Evaluation

> 状态：**设计完成，待实现**。任务入口 tasks.md。前置：V1~V7 全部完成。
> 设计原则：**评估是观察者**——只读旁路，不修改 Goal / Emotion / Memory / Response 的任何一个字节；评估失败只降级，绝不影响任何已产出的回答。

## 1. V7.5 解决什么问题

V7 为止，系统已具备完整的角色能力栈（Identity / Scene / Memory / Emotion / Relationship / Goal / Intention / Behavior / Autonomy），但这是一条**开环管线**——没有任何机制回答"这个角色做得好不好"：

```text
V7 为止（开环）：
User Message → Character Runtime → Response → 落库 → 后处理（结束）

V7.5（闭环观测，旁路）：
Response ──→ Evaluation Engine（异步旁路）
                ├─ Persona Check    这个回复像不像亚丝娜（OOC 检测）
                ├─ Emotion Check    情绪变化是否自然（跳变 / 无触发）
                ├─ Memory Check     记忆引用是否真实（False Memory）
                ├─ Behavior Check   动作是否越界 / 单调（V6.5 预算审计）
                └─ Autonomy Check   主动行为是否合理（V7 审计）
         ──→ Evaluation Report（五维评分 + Issue 清单 + 有界上下文摘要）
```

四个目前无法回答、V7.5 之后必须能回答的问题：

1. **这个回复是否符合角色？** 设定"温柔克制理性"，回复"暴躁辱骂"必须被发现（OOC）。
2. **这个情绪变化是否自然？** 用户普通聊天，角色突然极度悲伤——无触发跳变必须被发现。
3. **这个记忆是否应该使用？** 用户从没说过，角色却说"你最喜欢 xxx"——虚构记忆必须被发现。
4. **这个主动行为是否合理？** 用户刚回复角色立即再次主动；反之用户考试当天主动鼓励是合理的。

这些结果服务于两件事：**开发调试**（当轮定位质量缺陷）与**后续模型优化**（跨会话聚合 → 找出 prompt / 策略的系统性弱点）。

## 2. 硬边界（V7.5 明确不做）

- **不修改任何状态**：Goal / Emotion / Memory / Relationship / Scene / Response 一律只读。评估没有写回通道。
- **不阻断、不重试回答**：评估在出链后处理中异步执行，不进入聊天关键路径，不增加首 token 延迟。
- **不做自动调优**：V7.5 只产出报告与分数，不自动改 prompt / 策略 / 配置（V8+）。
- **不上用户侧**：所有评估产物只在 debug API 暴露，不进入前端聊天界面。
- **不存完整 Prompt**：报告只存有界上下文摘要（context digest），禁止保存 judge prompt 与完整消息历史，避免数据膨胀。
- **不引入第二套角色定义**：人格评估的事实源就是 `app/character/asuna/` 既有资产，不为评估复制一份描述。

## 3. 核心设计一览

| 概念 | 职责 | 形态 |
|---|---|---|
| EvaluationReport | 评估结果唯一载体：五维分数 + Issue 清单 + verdict | Pydantic 模型 + `evaluation_reports` 表 |
| EvaluationContext | 一次评估所需的全部数据切片 + 有界 digest | 纯函数收集器 |
| Rule Engine | 确定性规则判定（每轮必跑、零成本、可表驱动测试） | 纯函数注册表，severity → 扣分 |
| LLM Judge | 语义层判定（OOC / 情绪过度 / 虚构记忆确认） | 单次合并调用 + Pydantic 强 schema，一层降级 |
| 五维 Check | persona / emotion / memory / behavior / autonomy 各自的规则集 | `app/services/evaluation_rules/` |
| 挂载点 | 对话轮：post_process 第 7 步；主动行为：executor delivered 后；历史：离线评估器 | 旁路任务，失败只降级 |
| Persistence | 报告表 + 惰性保留清理；聚合视图按需派生不建表 | 迁移 0012 |
| Offline Evaluator | 从 DB 重建上下文批量评估历史会话 | 服务函数，fidelity=reconstructed |

分数语义一句话：**维度分 = 1 − Σ(命中规则扣分)，与 judge 分同时存在时取 min**——评估给出的是质量下界的估计，宁可偏严。

## 4. 文档导航

- [architecture.md](architecture.md) — 总体架构：两个实时挂载点 + 离线入口，与 Chat Request 的隔离，失败与降级（先读这篇）
- [evaluation-model.md](evaluation-model.md) — 域模型、Issue 编码表、分数语义、生命周期、配置组
- [persona-evaluation.md](persona-evaluation.md) — OOC 检测：词表硬信号 + judge 人格评审
- [emotion-evaluation.md](emotion-evaluation.md) — 情绪跳变 / 触发一致性 / 文本-状态冲突
- [memory-evaluation.md](memory-evaluation.md) — 虚构记忆 / 记忆矛盾 / 漏用
- [behavior-evaluation.md](behavior-evaluation.md) — 动作预算 / 接触越界 / 连续单调（纯规则）
- [autonomy-evaluation.md](autonomy-evaluation.md) — 主动行为时机 / 必要性 / 结果统计
- [rule-engine.md](rule-engine.md) — 规则协议、扣分表、注册表隔离
- [llm-judge.md](llm-judge.md) — 合并单调用设计、强 schema、evidence 自证、采样与降级
- [persistence.md](persistence.md) — 表结构、digest 上限、保留策略、三种评估范围
- [testing.md](testing.md) — 测试分层 + `tests/evaluation/` 场景套件
- [tasks.md](tasks.md) — 任务注册表（V7.5-001 ~ 015）

## 5. 关键架构事实

```text
1. 评估发生在出链：done 事件已 yield 给用户之后才启动，对聊天零延迟影响。
2. 规则每轮必跑（纯函数零成本），LLM judge 按 sample_rate 采样（默认 1.0，生产可调 0）。
3. judge 是单次合并调用：一个 prompt 同时评 persona / emotion / memory 三维，
   禁止每维独立调 LLM（3× 成本且输入高度重叠）。
4. 行为维接近 100% 规则可判：动作是文本层 *...* 描写，V6.5 的 observe_budget
   已经在做只读观测——V7.5 直接复用，不重复造轮子。
5. 主动行为是独立评估主体（subject=proactive_action）：它不是对话轮，
   没有 post_process，评估挂在 executor delivered 之后。
6. 结果统计（用户是否 ack / 是否回复）是离线聚合信号，不进实时单事件报告。
```
