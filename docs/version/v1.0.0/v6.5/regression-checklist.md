# V6.5 真实模型人工回归清单

> FakeLLM 只能验证 Behavior 层机制（映射/预算/稳定器）的正确性；「动作描写是否真的收敛、表现策略观感是否稳定、mode 是否不再跳变」必须以真实 LLM 回归为准。
> 执行：启动后端 + 前端，逐场景重放并核对 Debug 面板（turn_meta 的 behavior/mode 字段，或 `GET /api/v1/state` 的 mode/last_behavior）。与 V4/V5 清单（`docs/version/v1.0.0/v4/regression-checklist.md`、`docs/version/v1.0.0/v5/regression-checklist.md`）并列执行。

## 1. Action Budget 收敛（问题 1 的验收）

| 场景 | 操作 | 核对 |
|---|---|---|
| 日常闲聊 | default 模式连续 10 轮日常对话 | 单轮 `*动作描写*` ≤ 1（Debug：last_behavior.budget.max_action_desc=1）；无连续多轮堆叠动作 |
| 沉浸模式 | 连续 10 轮角色扮演/SAO 话题 | 单轮动作 ≤ 2，无「脸颊泛红+握手+整理衣领」三连 |
| 专业模式 | 连续 5 轮技术问题 | 零动作描写（budget.allow_action_desc=false），直接语言回应 |
| 强情绪 | 制造一次激烈冲突后观察 | intensity≥0.8 的轮次回复零动作（强情绪用语言） |

通过线：**单轮动作数 ≤ 预算上限的轮次占比 ≥ 90%**（LLM 偶发超预算可接受，连续超预算需调预算表或升级输出侧统计器 V6.5-010）。

## 2. Behavior Strategy 稳定性（问题 2 的验收）

| 场景 | 操作 | 核对 |
|---|---|---|
| 轨迹稳定 | 相同类型输入隔轮重复（如两次「我今天有点难过」） | Debug：strategy 一致（quiet_companion/direct_support），不随机漂移 |
| 安慰观感 | 连续 5 轮倾诉烦恼 | 先陪伴后建议的观感稳定；不一会儿说教一会儿撒娇 |
| 调侃分寸 | 关系亲昵后开玩笑 | playful_tease 点到为止；partner 档也不连环逗 |
| tension 收束 | 制造冲突至 tension>0.5 | strategy=reserved_distance，语气有保留；repair 意图时 sincere_repair 正常 |

## 3. Conversation Mode 稳定（问题 5 的验收）

| 场景 | 操作 | 核对 |
|---|---|---|
| 单轮跳变抑制 | 话题快速切换：技术→日常→情感→角色扮演，各 1 轮 | mode 保持 default 不跟随单轮话题跳变（R3 观望） |
| 迟滞切换 | 连续 2 轮以上明确角色扮演 | 第 2 轮起切 immersive 并写回（Debug：mode.switched=true） |
| 故障不跳变 | （可选）人为令 router 超时一次 | 生效 mode 保持 confirmed，不跳 default |
| 空闲回落 | 切 immersive 后闲置 2h 以上再发言 | mode 回落 default |

## 4. Activity 延续（问题 4 的验收）

| 轮 | 用户输入 | 核对 |
|---|---|---|
| 1 | 给我切个西瓜 | 回复执行动作；Debug：scene pending/engaged |
| 2 | 现在天气怎么样 | 回复自然带着「正在切西瓜」的状态边做边答（活动延续段生效）；不是凭空切换成天气播报 |
| 3 |（继续切完吧）| correct/continue_scene 路径正常，V3 directive 接管，无双重约束 |

## 5. Habit 观感（问题 3 的验收）

- 关心场景：观察「先做实际的事再开口」倾向是否出现（habit_care_action_first）。
- 安慰场景：先陪着等用户开口，不第一时间给建议（habit_comfort_companion_first）。
- 生气场景：克制、不升音量（habit_angry_restrained）。
- 提问节奏：单轮至多一个追问（habit_question_bounded）。
- 注意：habit 是倾向不是硬规则，观感出现率 ≥ 70% 即通过；professional 模式下不应有任何习惯色彩。

## 6. 性能

- SSE 首 token 时延与 V6 版本无可测量差异（V6.5 前台新增全部为纯函数，预期 <1ms）。

## 通过判定

- 以上场景全部命中；strategy/mode/预算误判案例记录 strategy.applied_rules 与 mode rule（R1~R5）反馈到映射表/稳定器迭代。
- 全量 `uv run pytest tests/ -v` 保持全绿。
- 若动作超预算率高：优先核对预算渲染是否进入 prompt（golden 快照），再考虑收紧预算表或启用 V6.5-010 观测。
