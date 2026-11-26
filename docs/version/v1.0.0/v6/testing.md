# V6 Testing

## 1. 约定

沿用：pytest + pytest-asyncio、FakeLLM（structured_responses 按 schema 名分发）、单元测试内存 SQLite、HTTP/e2e 走 TestClient、测试禁止真实 LLM。新增 `tests/golden/` 快照护栏。

## 2. 测试矩阵（14 项必测）

### Goal（1~6）

| # | Case | 断言 |
|---|---|---|
| 1 | 幂等播种 | 首次播种 3 条 persistent；重复播种零新增 |
| 2 | 冲突事件创建目标 | V5 conflict 事件 + tension≥0.5 → relationship 修复目标创建（幂等） |
| 3 | 疲惫创建目标 | user_emotion tired → user_care 陪伴目标创建 |
| 4 | 目标完成 | tension 回落 ≤0.3 → 修复目标 completed；emotion 恢复 → 陪伴目标 completed |
| 5 | 目标过期 | 超 expires_at_turn → expired |
| 6 | 用户语言边界 | "你应该喜欢我"不产生/修改任何 goal（policy 反例） |

### Selection & Conflict（7~9）

| # | Case | 断言 |
|---|---|---|
| 7 | tier 排序 | scene pending 存在时恒选 scene；否则 user_care > relationship > conversation |
| 8 | 上下文修正 | tension>0.5 时修复目标升至首位；深夜+疲惫时劝休升至首位 |
| 9 | 冲突裁决 | 凌晨+疲惫：陪伴 vs 劝休 → 劝休胜且陪伴入 suppressed；reason 可解释 |

### Intention（10~12）

| # | Case | 断言 |
|---|---|---|
| 10 | 相同 Goal 不同输入 | user_care 目标下：用户诉苦→comfort_user；用户说熬不住了→suggest_rest |
| 11 | Policy 有效性 | intimacy 低时 express_affection 降级；tension 低时 maintain_distance 降级；scene pending 时表达类降级 |
| 12 | 失败降级 | intention_chain 异常/非法输出 → continue_topic + trace degraded + SSE 完整（沿用 Case 9 模式） |

### Integration（13~14）

| # | Case | 断言 |
|---|---|---|
| 13 | 全链 | 消息→Goal 选择→Intention→Prompt 含目标/意图段→answer 正常；post_process goal_review 零冲突 |
| 14 | 回归 | `uv run pytest tests/ -v` 全绿；golden prompt：V1 无新段、V6 段落快照锁定 |

## 3. 附加单测文件

- `test_goal_models.py`：类型/状态/来源 Literal、priority 边界、description ≤40 字
- `test_goal_repository.py`：CRUD/幂等播种/状态过滤
- `test_goal_policy.py`：生命周期规则每条正反例、单轮 ≤1 创建、用户语言反例
- `test_goal_selection.py`：tier/修正/压制/空目标降级
- `test_goal_conflict.py`：矩阵表驱动 + 凌晨案例
- `test_intention_models.py`：枚举校验、decision schema、reason 截断
- `test_intention_policy.py`：有效性表逐条正反例、goal 一致性降级
- `test_intention_chain.py`：FakeLLM 候选输出、上限/None 处理
- `test_goal_context.py`：注入格式/预算/空值兼容/golden
- `test_goal_e2e.py`：编排接入（gather 4 链、turn_meta 携带 intention、SSE 零影响）

## 4. 真实模型回归（上线前人工）

- 动机可解释：连续对话后追问"你为什么这么回应"，trace 的 goal/intention/reason 与实际语气一致。
- 劝休场景：深夜疲惫聊天 → 角色自然建议休息且不赶人。
- 人格不丢：goal+intention 注入后回复仍是亚丝娜口吻（温柔地坚持/别扭地关心）。
- 无动机噪音：普通闲聊轮目标段不产生怪异话术、意图稳定为 continue_topic。
- SSE 首 token 时延与 V5 无可测量差异（4 链并行论证）。

## 5. 验收标准

14 项必测全绿 + 附加单测全绿 + V2~V5 零回归 + golden prompt 无意变更为零。
