# Testing

## 1. 组织方式

遵循项目既有分层规范（unit / integration / e2e + 主题前缀），**不新建 tests/v6.5/ 目录**——V5/V6 亦按主题分布（V6 用 test_goal_* / test_intention_*），保持一致：

| 层 | 文件 | 覆盖 |
|---|---|---|
| unit | `test_behavior_models.py` | 模型校验：枚举合法性、policy 键覆盖（mood 8 值/stage 4 档）、HabitRule 约束 |
| unit | `test_behavior_engine.py` | strategy 映射 12 项 + 修饰规则白名单逐条 + 降级路径 |
| unit | `test_action_budget.py` | 预算表矩阵（§3） |
| unit | `test_mode_stabilizer.py` | R1~R5 规则逐条 + 边界（恰好 2 轮/0.7 置信阈值） |
| unit | `test_behavior_context.py` | 【表现方式】/【活动延续】渲染：预算行触发条件、habit 去重、degraded fallback、_literal 转义 |
| unit | golden | 新增 `tests/golden/prompt_v65_full.txt` 快照 |
| integration | `test_behavior_pipeline.py` | chat_pipeline 接入：FakeLLM 全链路、turn_meta 契约、降级三处 |
| integration | `test_mode_persistence.py` | 迁移一致性、save_turn 同事务写回、存量行默认值 |
| integration | `test_activity_continuity.py` | 切西瓜场景：延续段注入 + Budget 减 1 + pending 时不双重注入 |
| integration | `test_behavior_consistency.py` | 行为一致性矩阵（§2） |
| e2e | `test_v65_matrix.py` | §2 十项矩阵聚合（HTTP 级，TestClient + FakeLLM） |
| e2e | 既有全量 | V2~V6 全部回归（§4） |

测试禁真实 LLM（AGENTS.md 既有铁律）；FakeLLM 的 `structured_responses` 注入各链输出。

## 2. 十项必测矩阵

### Behavior Consistency（行为一致性）

- **Case 1**：同一角色（同 state 快照），12 种 intention 输入 × FakeLLM → strategy 轨迹逐轮可复现（跑两遍结果全等）。
- **Case 2**：连续 10 轮 casual 对话，strategy 停留在 {natural_continuation, curious_inquiry, playful_tease} 族，不出现无修饰理由的 affectionate/reserved 跳变。
- **Case 3**：tension=0.6 + intention=express_affection → reserved_distance；intention=repair_rapport 时保持 sincere_repair（规则 2 白名单例外）。

### Action Budget（动作预算）

- **Case 4**：mode × stage × mood × strategy 关键组合 20 例，断言 max_action_desc/physical_contact/emotion_expression 全表（步骤 1~7 顺序与收紧单调性）。
- **Case 5**：professional 下 prompt 不含动作描写许可且含禁止句；quiet_companion 下 max=0 渲染「本轮不做动作描写」。
- **Case 6**：intensity≥0.8 时 max=0（强情绪不堆动作）。

### Habit（长期倾向）

- **Case 7**：comfort 类策略 → habit_care_action_first / habit_comfort_companion_first 按 priority 命中 ≤2 条；同向去重（quiet_companion 时不重复渲染陪伴 habit）。
- **Case 8**：focused_assistance（professional）→ matched_habits=[]。
- **Case 9**：Budget=0 + habit_care_action_first（行动表达）→ 渲染层裁决：habit 不注入动作许可，Budget 硬约束胜出。

### Activity（活动连续性）

- **Case 10**：current_action=切西瓜 + 用户问天气 → prompt 含【活动延续】段、Budget 减 1、strategy 不被活动改变；idle 会话两样都无；pending 场景 directive 优先且延续段不出现。

### Mode（模式稳定）

- **Case 11**：会话序列 default→(immersive 候选×1)→default→(immersive 候选×2 连续+conf≥0.7) → 前三轮生效 default，第四轮切换 immersive 且 DB 写回；之后 idle 2h 回落 default。
- **Case 12**：router 失败轮 → 生效=confirmed（不跳 default），trace 标 degraded。

### Regression（回归）

- **Case 13**：V2~V6 全量测试零回归；golden 快照仅允许新增 v65 文件，既有 v1/v5/v6 快照 diff 为零。
- **Case 14**：SSE 时序——含 behavior 段的请求 turn_meta 先于首个 token（现有契约不变），behavior_engine 耗时 <1ms。

## 3. golden 快照策略

- 新场景：analysis+goal+scene+behavior 全量输入 → `prompt_v65_full.txt`。
- 降级场景：intention 链失败 → 快照应含 V2【本轮行为指令】段而非【表现方式】段（fallback 语义固化）。
- UPDATE_GOLDEN=1 再生成，diff 必须逐行人工审（prompt 层 diff 纪律沿用）。

## 4. 全量回归口径

```bash
uv run pytest tests/ -v        # 全绿为提交门槛（沿用既有节奏）
```

V6.5 期间重点盯防：`test_prompt_golden`（builder 改动）、`test_scene_*`（RHYTHM 收口）、router 降级断言（故障语义改为保持 confirmed）、`test_v5_matrix` / `test_goal_matrix`（V5/V6 全绿）。

## 5. 真实模型人工回归

FakeLLM 无法验证「动作描写是否真的变少」——预算是 prompt 约束，其效力需真实模型观察。真实回归清单独立成文 `regression-checklist.md`（V6.5-010 P1），核心观察项：单轮动作数、strategy 跨轮稳定观感、mode 跳变频次、活动延续自然度。与 V4/V5 的既有 checklist 并列执行。
