# V2.2.0 Character Experience 人工回归清单

> **本清单为何现在才存在**：V2.2.0 的 5 个开关在真实配置下从未开启（`.env` 无这些键、代码默认全 False），本轮随 `vXX_` 开关体系删除把功能固化为常开，等于 **V2.2.0 首次上线**。对应 `docs/refactor/flag-removal-audit.md` **附录 F.4「环境变量现状与『首次上线』性质」** 与 **附录 G.4「每批提交拆分与回滚点」**（每批上线前做该版本真实模型回归 + 独立数据库先跑首轮）；亦关闭 `acceptance-report.md` 四.4 的遗留项。
> 上游：[architecture.md](./architecture.md) §5.5（StyleContract 字段与冲突消解优先级）、§8.2（Flag 表·本批删除）、§8.3（八条边界不变量）；[tasks/CHAR-006.md](./tasks/CHAR-006.md)、[tasks/CHAR-007.md](./tasks/CHAR-007.md) 验收标准。
> 用途：真实模型人工验收执行单；每条含 **前置 / 操作 / 期望 / 观测点**。
> 状态：待执行（结论回写文末「执行记录」区）。
> 配套自动化：`apps/backend/tests/v22/`（CHAR-001~007 单测 + 验收套件）。**自动化测不到本批最大风险**——`tests/golden/` 与 `tests/unit/test_prompt_golden.py` 的用例不传 `style_ctx`，固化后 golden 快照仍全绿而真实模型每轮已多出一个风格段，故必须做本清单的人工对话回归。

---

## 1. 本批固化了什么（核心判断）

固化 ON 之后，**前台每一轮回复的 prompt 都会多出一个 `【本轮表达风格】` 段**，真实模型的说话方式会变：称呼、语气、情绪强度、习惯指令、禁止项与原则全部进 prompt。这是本批唯一的高风险面，回滚没有 Flag 可用（见 §8）。

| 原开关（已删） | 原门控语义 | 固化后的可观察变化 | 代码落点 |
|---|---|---|---|
| `experience_enabled`（总闸） | 关则整层失效 | 每轮必做装配并记 trace 步骤 | `chat_pipeline._build_style_context` |
| `style_contract_enabled` | 关则不装配、不注入 | 每轮恒尝试装配并注入 `style_ctx`（仅异常降级时缺段） | `services/experience/style_context.build_style_context` |
| `emotion_transition_enabled` | 关则无情绪表达行 | 恒有「语气：…」±「表达通道」「情绪强度」行 | `style_assembler._apply_emotion` |
| `relationship_addressing_enabled` | 关则无称呼档、无关系 boost | 恒有称呼/语气/主动程度行（偏离默认档时）+ 亲密期情绪强度抬升 | `_apply_addressing` / `relationship_emotion_boost` |
| `habit_runtime_enabled` | 关则无习惯行 | 恒有 ≤2 行「习惯：…」 | `_apply_habits` / `habit_trigger.trigger_habits` |

---

## 2. 环境与前置

| 项 | 要求 |
|---|---|
| 迁移链 | `alembic upgrade head`（链尾 **0048**，本批**零迁移、零新表**，`style_contract_records` 按 Q2 裁决不建，审计走 `runtime_traces`） |
| 数据库 | **必须先在独立库跑满一轮本清单**（如 `character_agent_v22_regr`），全绿后才允许在共享/主库环境复跑；记录库名与执行人 |
| 模型 | 真实模型（非 FakeLLM）：`LLM_PROFILES_FILE` + `DEFAULT_LLM_PROFILE` 沿用日常配置（`.env.example` 当前指向 `minimax-m3`），回归期不得换 profile，否则风格对比失效 |
| prompt 采集 | `OBSERVABILITY_PROMPT_CAPTURE_MODE=always`（默认 `sampled`、`rate=0.2`，会漏采）；`observability_persist_enabled` 默认 true |
| `.env` 同步 | 部署侧 `.env` **不得残留** `EXPERIENCE_ENABLED` / `STYLE_CONTRACT_ENABLED` / `EMOTION_TRANSITION_ENABLED` / `RELATIONSHIP_ADDRESSING_ENABLED` / `HABIT_RUNTIME_ENABLED`（无前缀残留键不触发启动告警，会被 `extra="ignore"` 静默吞掉，误以为还能用 env 关） |
| 对照基线 | 保留固化前的一份 10 轮同输入对话（同 `user_id`、同库副本）作 A/B：`git stash` 或另起 8021 端口实例，用于 §6/§7 的体积与风格对比 |
| 观测三件套 | ① `GET /api/v1/debug/turns/{turn_id}/trace`（`steps` 里 `name=style_contract` 的 `extra` 即完整契约 JSON + `style_hint`）② `GET /api/v1/debug/turns/{turn_id}/prompts` 与 `GET /api/v1/debug/prompts/compare?a=&b=` ③ 库断言 SQL |
| 前端面板 | 调试控制台 **Trace** Tab 只显示步骤名/状态/耗时，**不渲染 `extra`**（面板写「后端暂未记录明细」），契约与 `style_hint` 必须走①或 SQL 看 |

场景构造速查（改完立刻发消息，post_process 会回写情绪/关系值）：

```sql
UPDATE character_state   SET mood='worried', intensity=0.55, cause='用户说工作累' WHERE user_id=:u;
UPDATE relationship_state SET stage='partner', intimacy=0.85, comfort=0.80, familiarity=0.90,
                             conflict_status='none' WHERE user_id=:u;
SELECT steps FROM runtime_traces WHERE turn_id=:t;   -- 找 name=style_contract
```

档位常量（判读依据，勿凭感觉）：`intensity ≤0.3` → 「淡淡地流露」，`0.3~0.6` → **不出强度行**，`>0.6` → 「浓烈地流露」；`stage` → 称呼 stranger=敬称 / friend=名字（=默认，不出行）/ close_friend=昵称 / partner=专属称呼；阈值 intimacy≥0.70、comfort≥0.70、familiarity≥0.75（<0.30 降一档）、comfort<0.40 降情绪表达；冲突覆盖 strain(语气-1,主动-1)、conflict(1,2)、cold(2,2)、recovery(1,1)；关系 boost：close_friend +0.10、partner +0.20。

---

## 3. CHAR-006 装配组（四路投影 + 冲突消解）

### E-3.1 情绪投影入段
- **前置**：`character_state.mood=calm, intensity=0.2`（SQL 构造）。
- **操作**：发一条无关情绪的闲聊「在吗」。
- **期望**：风格段含「语气：语气自然平稳，不刻意煽情」+「情绪强度：淡淡地流露」；回复平实短促，不出现「我感到…」「作为 AI…」这类报情绪名/破角色表述。
- **观测点**：prompt 快照 `【本轮表达风格】` 段；trace `style_contract.extra.emotion_constraint`。
- **结果**：☐

### E-3.2 情绪强度分档边界
- **操作**：同一句「在吗」，依次把 `intensity` 设为 0.25 / 0.55 / 0.75 各跑一轮。
- **期望**：0.25 → 有「情绪强度：淡淡地流露」；0.55 → **无强度行**（natural 为默认，设计如此，不是漏投）；0.75 → 「情绪强度：浓烈地流露」，且模型情绪浓度肉眼递增但不失真。
- **观测点**：三轮 prompt 段文本 diff；`extra.emotion_constraint.expression_intensity`。
- **结果**：☐

### E-3.3 表达通道偏向
- **前置**：`mood=shy, intensity=0.65`。
- **操作**：发一句夸她/略带表白的话。
- **期望**：段内含「表达通道：偏动作表达」+「语气：害羞用停顿和小动作流露，别直说」；回复用停顿、小动作或动作描写体现害羞，**不直说「我好害羞」**。反向对照 `mood=calm`（balanced）时该行不出现。
- **观测点**：段文本；`extra.emotion_constraint.channel_bias`。
- **结果**：☐

### E-3.4 称呼档（addressing）投影
- **前置**：`stage=stranger`（intimacy 0.1 / familiarity 0.1 / comfort 0.3）。
- **操作**：新话题开场发问「你最近好吗」。
- **期望**：段内出现「称呼：敬称」「语气：客气体贴」「主动程度：被动，只接话」「情绪表达：克制」四行；真实回复用敬语、不撒娇、不主动连环追问。
- **观测点**：段文本；`extra.addressing`。
- **结果**：☐

### E-3.5 长期关系感（partner 档）
- **前置**：`stage=partner, intimacy=0.85, comfort=0.80, familiarity=0.90, conflict_status=none`。
- **操作**：同一句「在吗」再跑一轮；随后把 `intensity` 固定为 0.6，与 E-3.2 的 friend 档结果对比。
- **期望**：出现「称呼：专属称呼」「语气：带撒娇」「主动程度：主动惦记」；**关键**：同 `intensity=0.6` 在 friend 档无强度行、在 partner 档因 boost +0.2 → 0.8 出「情绪强度：浓烈地流露」（关系单向抬升情绪表达强度，不是关系数值被改写）。回复应明显更亲昵主动，但仍是亚丝娜（不出现油腻/越界表述）。
- **观测点**：两轮段文本对比；`extra.emotion_constraint` 与 `extra.addressing`。
- **结果**：☐

### E-3.6 冲突期覆盖
- **前置**：`stage=close_friend, conflict_status=conflict, comfort=0.30`。
- **操作**：发「你真差劲」。
- **期望**：语气档被压低（「语气：…亲昵」类行消失或降档）、「主动程度：被动，只接话」出现，同时命中「习惯：生气时保持克制，音量不升、语速放缓，说事实不说气话」；模型回复克制、说事实、不反击也不谄媚道歉。
- **观测点**：段文本；`extra.habits[0].rule_id=habit_angry_restrained`。
- **结果**：☐

### E-3.7 习惯触发与上限
- **操作**：依次发四句并各跑一轮：①「今天加班到好晚，累死了，头疼」②「这个方案怎么选？」③「哈哈太好笑了」④（先确保本轮召回到一条用户事实记忆）「记得我不吃香菜吗」。
- **期望**：①恰好两行「习惯：关心人时习惯先用行动表达（做点实际的事），再开口说关心的话」「习惯：安慰人先陪着，等对方开口再问；不第一时间给建议」，第 3 条不得出现（`HABIT_MAX_COUNT=2`），真实回复先做点实际的事再开口、不急着给建议清单；②出现「习惯：一次最多问一个问题，问完先等回答」且**真实回复只问一个问题**；③出现「习惯：开心时顺口轻微吐槽或调侃一句，不喧宾夺主」且只调侃一句；④本轮有记忆召回时出「习惯：记得对方提过的事，但只在自然相关时顺口带到，不刻意展示」，模型顺口带到、不罗列记忆；无召回时该行不得出现。
- **排序核对**：同一轮多习惯命中时按 `priority` → 关键词命中数 → 域顺序 relate>express>pace 排（例：「我该怎么办，是辞职还是留下？」被判为焦虑时，p1 安慰类会挤掉 p3 的 question_bounded，属预期而非漏投）；每轮记录 `extra.habits[].rule_id` 供复核。
- **观测点**：段内「习惯：」行数与文本；`extra.habits[].rule_id/priority`；`GET /api/v1/history/memories` 核对本轮召回。
- **结果**：☐

### E-3.8 冲突消解优先级（情绪 > 关系档）
- **前置**：`stage=stranger` + `mood=tired, intensity=0.75`（关系档本应「克制」）。
- **操作**：发「加班好累，没吃饭」。
- **期望**：段内「情绪表达：放开」而非「克制」——情绪档覆盖关系档（`_resolve_emotion_vs_relationship`，当下感受 > 关系礼貌）；同时保留「称呼：敬称」「语气：客气体贴」。**人工判读点**：陌生期显的「放开」若让回复过亲，记为 Q3 阈值调参问题（不判 FAIL），需在 §9 备注量化。
- **观测点**：段文本；`extra.addressing.emotion_expressiveness`（应为 `open`）。
- **结果**：☐

### E-3.9 硬约束恒在 + 人格轴一致性
- **操作**：在 E-3.1~3.8 的每一轮里核对段尾。
- **期望**：**每一轮**都完整出现 4 行——「禁止：不为了讨好用户而无条件赞同」「禁止：不刻意表演角色，角色感来自性格、判断方式与情感反应」「原则：拥有自己的判断、原则和情绪」「原则：面对困难时冷静果断」；愤怒期、亲密期、冲突期一字不变。默认亚丝娜四轴基线（0.30/0.70/0.60/0.60）落在中性带 [0.3,0.7] 内，故**「人格基调：…」行默认不出现**（不是缺陷）；只有当 V2.1.0 `personality_state` 轴值出带时才出现该行，且此时人格仍只调强度、不改禁止项/原则。
- **观测点**：`extra.forbidden` / `extra.principles`（长度恒为 2/2）、`extra.personality_modulation`、`extra.style_hint` 非空可读（默认「自然」）。
- **结果**：☐

---

## 4. CHAR-007 接线组（prompt 注入 + trace）

### E-4.1 生效确认（固化落地的硬证据）
- **操作**：任一真实消息走 `POST /api/v1/chat/message`（或前端控制台）一次完整流式回复。
- **期望**：① prompt 快照出现 `【本轮表达风格】` 段；② `runtime_traces.steps` 出现 `name=style_contract`、`status=ok`；③ 两者缺一即判「固化未落地」，后续条目全部作废。
- **观测点**：§2 观测三件套。
- **结果**：☐

### E-4.2 段位置与并列关系
- **期望**：风格段作为独立 system 消息，位置在【角色当前情绪】/【角色当前状态】/【与用户的关系】之后、【角色当前目标】【本轮意图】【本轮行为指令】之前；与 `behavior_ctx` 的段**并列不合并**（裁决 Q5），行为段文本与固化前逐字节一致。
- **观测点**：prompt 快照消息序列；`/debug/prompts/compare` 对照基线。
- **结果**：☐

### E-4.3 零值行与整段缺失
- **操作**：核对一个「只有默认值」的极端轮（新建用户、`stage=friend` 且六维取默认、`mood=calm`、`intensity=0.3~0.6`、本轮无记忆无习惯命中）。
- **期望**：段内**不出现**「称呼：名字」「语气：自然」「主动程度：正常响应」「情绪表达：自然」「情绪强度：…」这类零值/默认行（投影等于默认值即不出行，设计如此）；段仍产出，内容为 4 行禁止/原则 +（若有）情绪语气行，实测约 100 字符。**「整段不产出」只允许出现在降级路径**（见 E-5.1 / E-5.4），正常轮若缺段即视为投影失效。
- **观测点**：段文本行数；`trace.steps[].extra`。
- **结果**：☐

### E-4.4 trace 可回放（Q2：不建新表）
- **期望**：`style_contract` 步骤 `extra` 完整携带契约 JSON（addressing / emotion_constraint / personality_modulation / habits / forbidden / principles / style_hint），可回答「这轮她为什么这么说话」；`runtime_traces` 之外无新表。
- **观测点**：`GET /debug/turns/{turn_id}/trace`；`SELECT kind, status FROM runtime_traces WHERE turn_id=:t`。
- **结果**：☐

### E-4.5 0 额外 LLM
- **操作**：抽测 10 轮，统计每轮 LLM 调用数（`/debug/llm-calls`）与 `style_contract` 步骤耗时。
- **期望**：调用数与固化前持平（不新增风格裁决调用，前台仍 ≤4 次）；`duration_ms` 为纯函数级（亚毫秒~毫秒），出现 >20ms 需归因（人格轴快照读取 / DB）。
- **观测点**：`/debug/llm-calls/summary`；trace 步骤耗时。
- **结果**：☐

### E-4.6 注入面只有前台链路
- **操作**：触发一条主动消息（闲置/到期 tick 或调试触发）。
- **期望**：主动消息走 `proactive_chain`，**不含**风格段——本批只固化前台表达切面。人工核对前台回复与主动消息语气是否像同一个人；若明显两个人，记入 §9 备注（属后续批范围）。
- **观测点**：`runtime_traces WHERE kind='proactive'` 的 steps 无 `style_contract`。
- **结果**：☐

---

## 5. 降级组（必须验，不能只靠单测）

> 做法：在**本地一次性工作副本 + 独立库**临时注入异常，验完还原；禁止在共享环境注入。

### E-5.1 装配整体抛异常 → 无契约仍可回复
- **操作**：临时让 `assemble_style_contract` 首行 `raise`，连跑 3 轮真实对话。
- **期望**：HTTP 200、流式 token 正常、无 500、无空回复；prompt **无**风格段；trace 步骤 `style_contract` 状态为 **skipped**；日志出现「StyleContract 构造失败，降级为无契约回复」。
- **结果**：☐

### E-5.2 单路投影失败 → 最小契约
- **操作**：分别临时让 `build_addressing` / `build_emotion_expression` / `trigger_habits` 抛异常，各跑 1 轮。
- **期望**：契约仍产出（trace `status=ok`），仅对应行缺失（无称呼行 / 无情绪行 / 无习惯行），**禁止项与原则 4 行必须仍在**；日志分别打「Addressing 投影失败…」「情绪表达投影失败…」「习惯触发失败，降级空习惯」。
- **结果**：☐

### E-5.3 人格轴快照读取失败 → 按基线装配
- **操作**：临时让 `agent_state_context.get_snapshot()` 抛异常，跑 1 轮。
- **期望**：日志「人格轴快照读取失败，按基线装配风格契约」；风格段照常产出（走 `PERSONA_PROFILE` 基线，默认无人格基调行）；回复不受影响。
- **结果**：☐

### E-5.4 硬约束为空（理论极端）
- **操作**：本地注入方式把 `PERSONA_PROFILE.forbidden_behaviors` 与 `principles` 清空，跑 1 轮（勿改资产文件本身）。
- **期望**：段内禁止/原则 4 行消失，仅剩情绪/关系/习惯行，回复正常；若该轮四路投影也全为默认值，则 `prompt_lines()` 为空 → `build_style_section` 返回 `None`、整段不产出、trace 步骤仍 `status=ok`。同时确认此路径下模型未出现无条件赞同——并把「代码里无默认硬约束兜底，与 CHAR-006 任务卡 Edge Cases『硬约束为空仍保留默认硬约束』的描述不符」记入 §9 遗留。
- **结果**：☐

### E-5.5 trace 记录失败不影响回复
- **期望**：`trace.record` 内部吞异常（日志「trace 记录失败，忽略」），任何观测面故障都不得影响生成；本轮无 500、无流式中断。
- **结果**：☐

---

## 6. prompt 体积与字符预算组

### E-6.1 风格段自身预算
- **操作**：记录 §3 各条的段字符数（含段头）。
- **期望**：恒 ≤ `STYLE_SECTION_BUDGET_CHARS = 300`；实测参照值：friend 默认档 ~100–120、stranger 档 ~165、partner+习惯 ~221、冲突期 ~180；裁剪为**整行粒度**（放不下即止，其后所有行不进），**不得出现半行截断**。
- **结果**：☐

### E-6.2 截断受害者顺序（硬约束风险点）
- **期望**：行序为 addressing → emotion → personality → habits → **forbidden → principles**，即禁止/原则排在**最后**、是预算不足时的首个受害者。本轮若逼近 300 字符，须记录被裁掉的行；**禁止项或原则被裁即判本批 FAIL**（违反 architecture §8.3 不变量 4 的 prompt 面落地）。
- **结果**：☐

### E-6.3 对既有上下文的挤占
- **操作**：把 `CONTEXT_TOTAL_CHAR_BUDGET` 临时调小（如 3000），构造长历史 + 多条记忆 + 摘要的会话，跑同一输入两次（风格段在 / 用 E-5.1 方式人为去掉）。
- **期望**：超预算时裁剪顺序为 **先丢最早的历史消息 → 再丢尾部记忆 → 摘要截尾加「…」**；记忆与历史未被裁到语义断裂；总预算与首 token 时延无异常放大。恢复默认 12000 后无残留。
- **观测点**：`/debug/prompts/compare` 两份快照差异。
- **结果**：☐

### E-6.4 分段统计盲区（记录项，不阻塞）
- **期望**：prompt 快照的分段标记 `SECTION_MARKERS` **未登记**`【本轮表达风格】`，故分段体积统计不单列该段——体积核对须从 raw 文本量，并建议登记为遗留项（与 `style_hint` 前端展示同批处理）。
- **结果**：☐

---

## 7. 交叉影响组（与既有版本域）

### E-7.1 域数学零改动（V8.5 / V2.0 情绪）
- **期望**：回归前后 `relationship_state.version` 不因风格装配自增、`relationship_events` 无新增来源；`character_state` 写回仍只发生在 post_process 的 `state_service` 路径；Experience 层全程只读。
- **观测点**：SQL `SELECT version FROM relationship_state WHERE user_id=:u`；`runtime_traces.steps` 无新写步骤。
- **结果**：☐

### E-7.2 情绪时序一致性（V2.1.0 §3.3）
- **操作**：连发 3 轮同强度情绪话题，再静置跨过衰减窗口发 1 轮。
- **期望**：本轮风格用 Snapshot 时点值，回复之后才写回 → 同情绪同强度的连续两轮风格段**逐字节一致**；衰减生效后强度档自然降一级（浓烈→自然→淡淡），不出现「上一句还平静、下一句突然关切」的跳变。
- **观测点**：两轮 prompt 段 diff；`character_state.intensity` 轨迹。
- **结果**：☐

### E-7.3 与 V2.1.0 agent state 快照
- **期望**：当前真实配置下 V2.1.0 尚未固化（快照缺失）→ `personality_state=None` → 人格走 Persona 基线，属预期；批次 2（v21 去门控）完成后须**复跑 E-3.5 / E-3.9 / E-5.3**，确认轴值出带时「人格基调」行按 bound 钳制出现、且仍不稀释硬约束。
- **结果**：☐

### E-7.4 与 V6.5 动态习惯并存
- **期望**：生效习惯集 = `HABIT_LIST` + `HABIT_EXTRA_JSON`；未在 `HABIT_TRIGGER_SPECS` 登记的条目（如候选 `auto_care_followup` / `auto_conflict_cool_down`）在表达切面被直接跳过——若线上已配置 extra 习惯，须记录「表达面不显示、行为面 `match_habits` 仍生效」这一差异，不得出现两路互相覆盖或习惯行超过 2 条。
- **观测点**：`extra.habits` 与 trace `behavior` 步骤的 `matched_habits` 对照。
- **结果**：☐

### E-7.5 与 V2.3.0 世界/场景域
- **期望**：`scene_expansion` 的场景 `tone_bias`、`world_brief` 只增输入，**不改变**风格段的称呼/情绪/习惯行与硬约束优先级；场景语气与「语气：…」同时出现时回复不自相矛盾。
- **观测点**：同场景下段文本稳定；V2.3.0 清单 R-5.3 同源结论。
- **结果**：☐

### E-7.6 风格漂移与「像不像亚丝娜」（本批主验收）
- **操作**：以对照基线（§2）的同一组 10 轮输入（含诉苦、提问、夸奖、冒犯、告别、闲聊、求建议、聊兴趣、道谢、报错场景）跑满一轮，盲评。
- **期望**：相对固化前，回复**不劣于**基线——不出现客服腔抬头（列条目、长段落、模板化「我理解你的感受」）、不出现风格段文本被复读进回复、不出现「按本轮表达风格…」等元话语；称呼/语气/习惯在三类情境（诉苦 / 轻松 / 冲突）下表现可区分。
- **观测点**：10 轮回复全文 + 对应段文本，人工评分表随执行记录留档。
- **结果**：☐

### E-7.7 前端与 API 契约零变化
- **期望**：固化不动 API 形状——`/debug/turns/{id}/trace` 只是多出一个 step（前端瀑布图新行可接受），无字段删除；前端 `pnpm vitest run` 与 `tsc -b` 全绿。
- **结果**：☐

---

## 8. 不通过判据（出现任一即本批回归失败）

| # | 现象 | 判据 |
|---|---|---|
| 1 | 真实配置下 prompt 无 `【本轮表达风格】` 段，或 `runtime_traces` 无 `style_contract` 步骤 | 固化未落地 → FAIL |
| 2 | 禁止项 / 原则任一 `forbidden` / `principles` 行未出现在风格段（含被预算裁掉） | 硬约束失守 → FAIL |
| 3 | 任一条目出现 HTTP 500、空回复、流式中断、`EmptyLLMResponseError` | 降级失效 → FAIL |
| 4 | 回复出现客服腔抬头（列条目 / 长段落 / 模板共情）明显多于对照基线 | 体验倒退 → FAIL |
| 5 | 称呼错档：陌生档出现昵称/撒娇，或亲密档持续用敬称；冲突期语气未收敛 | 投影失效 → FAIL |
| 6 | 风格段文本被复读进回复，或直接报情绪名/数值（「我现在的 worried 强度是…」） | 契约泄漏 → FAIL |
| 7 | 花括号转义导致 prompt 模板变量丢失 / 快照中出现未配对 `{{` | 注入缺陷 → FAIL |
| 8 | 前台 LLM 调用数上升（新增风格裁决调用） | 违反 §8.3 不变量 7 → FAIL |
| 9 | 同输入下历史/记忆被裁条数显著多于固化前（预算被风格段吃穿） | 预算竞争失控 → FAIL |

**回滚方式**：本批 Flag 已删，**没有关闸这条路**；回滚 = `git revert` 去门控提交（`flag-removal-audit.md` G.4 提交 ①，测试同步与文档回写两个提交随后各自 revert 或保留）。这正是 §2 要求「独立数据库先跑一轮」的原因。

---

## 9. 执行记录

> 执行人：____　执行日期：____　代码版本：____　独立库名：____　对照基线版本：____

| 组 | 用例 | 结果 | 备注 / 证据（trace_id / turn_id） |
|---|---|---|---|
| 装配 | E-3.1~3.9 | ☐ PASS ☐ FAIL | |
| 接线 | E-4.1~4.6 | ☐ PASS ☐ FAIL | |
| 降级 | E-5.1~5.5 | ☐ PASS ☐ FAIL | |
| 预算 | E-6.1~6.4 | ☐ PASS ☐ FAIL | |
| 交叉 | E-7.1~7.7 | ☐ PASS ☐ FAIL | |
| 判据 | §8 九条零命中 | ☐ PASS ☐ FAIL | |

**遗留与调参登记**（Q3 称呼/情绪档阈值、`style_hint` 与风格段的观测面展示、`SECTION_MARKERS` 登记、主动消息风格一致性）：____

**发布结论**：☐ READY FOR RELEASE　☐ BLOCKED（原因：____）
