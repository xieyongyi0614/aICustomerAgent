# Intention Integration（V7 × Intention）

## 1. 主动场景的 Intention 生成方式

与 V6 反应式不同，主动场景**没有用户消息**，LLM 决策链（intention_chain）的输入不完整。因此：

```text
反应式（V6）：intention_chain(LLM) → IntentionPolicy
主动式（V7）：Goal 类型 → PROACTIVE_INTENTION_MAP（确定性）→ IntentionPolicy 校验
```

理由：主动行为的风险不对称——错误地主动一次的代价远大于漏掉一次；确定性映射把 LLM 从"是否行动"的关键路径上完全摘掉，LLM 只负责最后"说什么"（proactive_chain）。

## 2. IntentionPolicy 复用

proactive intention 仍走 `intention_policy.enforce` 的**有效性子集**：

| intention | 校验（V6 规则复用） |
|---|---|
| check_in | 恒合法（新增值，V7-001 注册进 IntentionType） |
| repair_rapport | tension ≥ 0.3（V6 既有规则） |

Policy 其余 goal 一致性检查天然通过（映射表即按 goal 类型构造）。

## 3. 与 turn_meta / trace 的关系

- 主动行为不产生 turn_meta（无用户请求），改由 **trace 独立会话**记录：step `autonomy_policy`（verdict）、`proactive_generate`（LLM 文本生成）、`proactive_deliver`（落库）。
- action 行本身保存 intention/reason/verdict 快照——"角色为什么主动说这句话"由 `GET /proactive/pending` 与 debug 可查。

## 4. 未来演进（记录，不实现）

- V8 可让主动场景也走 LLM 意图决策（输入环境信号而非用户消息），并把 PROACTIVE_INTENTION_MAP 扩展为打分制；
- 多 Trigger 竞争排序（同时到期多个事件）→ AutonomyVerdict 增加 confidence 字段；
- 这些都不影响 V7 的表结构（action 行存 type/reason，天然兼容）。
