# V2 角色状态系统架构设计（Character State System）

> 目标：让「亚丝娜」从「记住发生过什么」（Memory）升级为「知道自己现在是什么状态」（Character State）。
> 前提：V1 记忆系统全部保留不动，V2 全部为**增量接入**。
> 约束：不引入 LangGraph、不做 Multi Agent、不重构 V1 Memory、保持 LangChain + LCEL、优先保证人格稳定性、状态设计预留 LangGraph 迁移、不过度设计。

---

## 1. V1 现状分析与 V2 接入点

### 1.1 V1 编排现状（已核实代码）

```
POST /api/v1/chat/message
 └─ agent_service.stream_chat（services/agent_service.py:16）
     ├─ context_builder.build      → ConversationState（窗口 + 摘要 + 记忆检索）
     ├─ router_chain.route         → RoleMode（structured output，低置信降级 default）
     ├─ answer_chain.astream       → PromptBuilder.build(mode, state) | llm 流式
     ├─ conversation_service.save_turn
     └─ asyncio.create_task(_post_process)
          ├─ 阈值触发 summary_service.update
          └─ memory_service.extract_and_save（should_save 且 importance≥0.6，带去重）
```

### 1.2 V1 的缺口（V2 要补的）

| # | 缺口 | 现状 |
|---|------|------|
| G1 | 角色无内在状态 | 人格是 `character/asuna/` 下 5 个**静态常量**，聊 100 轮和第 1 轮的「亚丝娜」完全一样 |
| G2 | 关系不演化 | `RELATIONSHIP_BLOCK` 固定文案；`relationship` 只是 memory_type 枚举值，不是可演化的状态 |
| G3 | 行为单一 | 只有 mode 三档（语言风格），没有「安慰 / 庆祝 / 关心」这类**行为意图**决策 |
| G4 | 对用户情绪无感知 | 用户说「项目上线了」和「我今天压力很大」，角色侧没有任何差异化的状态输入 |

### 1.3 V2 接入点（全部是「插入」，不改 V1 Memory）

| 接入点 | V2 改动 | 涉及文件 |
|---|---|---|
| 上下文构建 | 增读 character_state / relationship_state 填入 ConversationState（含闲置恢复） | `services/context_builder.py`、`models/conversation.py` |
| 预侧编排 | router 与 turn_analysis 链 `asyncio.gather` 并发，失败各自降级 | `services/agent_service.py` |
| Prompt 组装 | 新增 3 个 system section：角色当前状态 / 与用户的关系 / 本轮行为指令 | `prompts/builder.py`、`chains/answer_chain.py` |
| 后处理 | 追加状态更新（LLM 决策 + 确定性规则）与 emotion_history 落库，与摘要 / 记忆提取互不影响 | `services/agent_service.py`、`services/state_service.py` |
| 数据层 | 追加 3 张 ORM 表（lifespan `create_all` 只增不改，零迁移成本） | `core/db.py` |
| 配置 | 新增状态相关阈值 | `core/settings.py` |

---

## 2. V2 总体架构

```
User
 ↓
┌─ asyncio.gather 并发（互不依赖）─────────────────────────────┐
│ Role Router（V1 不动）        Turn Analyzer（新，一次结构化输出：  │
│ → mode / confidence            user_emotion + event + behavior） │
└────────────────────────┬────────────────────────────────────┘
                         ↓ 失败各自降级：default / neutral+daily+normal_reply
Context Builder（V1 扩展）：短期窗口 + 摘要 + 记忆检索
                         + CharacterState + RelationshipState（含闲置恢复）
                         ↓
Prompt Builder（模块化 section，新增：角色当前状态 / 与用户的关系 / 本轮行为指令）
                         ↓
Asuna Agent（answer_chain 流式，NDJSON 契约不变）
                         ↓
Response → save_turn → 后台 fire-and-forget（各环节 try/except 隔离）：
  ├─ State Update Engine：
  │    StateUpdater LLM（mood / inner_state / current_topic，失败→纯代码规则）
  │    → state_engine 确定性规则（energy 衰减与恢复 / relationship 三维 delta / stage 阈值迁移）
  │    → character_state + relationship_state upsert + emotion_history 追加
  ├─ Memory Extractor（V1 不动）
  └─ 滚动摘要（V1 不动，达阈值才触发）
```

**LLM 调用预算**：预侧 2 次（router ∥ turn_analysis 并发，墙钟延迟≈V1 的 1 次）；后台 2 次（state_update + extractor）+ 偶发摘要。首字延迟不因 V2 显著劣化。

**关键决策（Decision Records）**：

| # | 决策 | 理由 |
|---|------|------|
| D1 | 情绪 + 事件 + 行为**合并为一次**结构化输出（`TurnAnalysis`），并与路由**并发**执行 | 三者同源（都看用户消息 + 上下文），拆三次串行调用会把首字前的 LLM 调用从 2 次拉到 4 次；合并后墙钟≈V1。模块边界仍保留（独立模型文件 / 独立链），只是共享一次调用（已与用户确认） |
| D2 | 关系三维**数值不直接进 prompt**，转换为阶段文案 + 定性档位 | 「intimacy=0.73」这类数字会破坏人格稳定性，LLM 也难以稳定消费 |
| D3 | stage 阈值 / energy 参数进 `settings.py`；事件→delta 完整映射表保留为 `state_engine` 模块常量 | 阈值属环境配置（AGENTS.md 要求）；delta 映射属领域规则，进 settings 会把配置面撑爆 |
| D4 | 初始 `stage=friend`（0.3 / 0.35 / 0.3） | 人设默认用户=桐人，已有基础羁绊；同时留出向 close_friend / partner 成长的空间 |
| D5 | 状态写入只发生在后处理 | 延续 V1「读取进链、写入出链」，写入失败不拖垮对话 |

**降级矩阵（人格稳定性优先）**：

| 环节 | 失败表现 | 降级行为 |
|---|---|---|
| Role Router | 异常 / 低置信 | `mode=default`（V1 已有） |
| Turn Analyzer | 异常 / 解析失败 | 默认 `TurnAnalysis`（neutral / daily / normal_reply），回答照常 |
| StateUpdater LLM | 异常 / 解析失败 | `decision=None` → 纯代码规则照常更新 energy / relationship，mood 保持旧值 |
| 三表写入 | 异常 | 记日志，不影响本轮回答与其余后处理 |

**已知限制**：同一 user_id 并发两轮对话时，后处理使用的预侧状态快照可能互相覆盖（last-write-wins）。当前单用户串行客户端场景可接受，多用户时需按 user 加锁或改乐观并发，记入 V2 P2 backlog。

---

## 3. Pydantic 模型设计（`app/models/`）

全部为**可序列化纯 DTO**，不跨层传 ORM 对象——这是 LangGraph checkpoint 迁移的前提。

```python
# models/behavior.py
BehaviorType = Literal[
    "normal_reply", "comfort", "encourage", "celebrate",
    "show_concern", "recall_memory", "ask_followup",
]

class BehaviorDecision(BaseModel):
    behavior: BehaviorType = "normal_reply"
    reason: str = ""


# models/emotion.py
UserEmotionLabel = Literal[
    "happy", "calm", "sad", "anxious", "angry",
    "tired", "excited", "neutral",
]
EventCategory = Literal[
    "achievement", "setback", "share_goal", "seek_help",
    "help_given", "complaint", "conflict", "daily", "farewell",
]

class UserEmotion(BaseModel):
    emotion: UserEmotionLabel = "neutral"
    event: EventCategory = "daily"

class TurnAnalysis(BaseModel):
    user_emotion: UserEmotion = UserEmotion()
    behavior: BehaviorDecision = BehaviorDecision()


# models/character_state.py
Mood = Literal["happy", "calm", "worried", "sad", "shy", "excited", "tired", "angry"]

class CharacterState(BaseModel):
    mood: Mood = "calm"
    energy: float = Field(default=0.9, ge=0.0, le=1.0)
    current_topic: str = ""
    inner_state: str = "平静，期待和用户聊天"
    updated_at: datetime | None = None      # 闲置恢复的基准，仅由 repository 填充

class StateUpdateDecision(BaseModel):       # StateUpdater LLM 的输出
    mood: Mood
    mood_reason: str = ""                   # 便于日志观测与调试
    inner_state: str
    current_topic: str


# models/relationship.py
RelationshipStage = Literal["stranger", "friend", "close_friend", "partner"]

class RelationshipState(BaseModel):
    intimacy: float = Field(default=0.3, ge=0.0, le=1.0)      # 亲密
    trust: float = Field(default=0.35, ge=0.0, le=1.0)        # 信任
    familiarity: float = Field(default=0.3, ge=0.0, le=1.0)   # 熟悉
    stage: RelationshipStage = "friend"

class RelationshipDelta(BaseModel):        # state_engine 内部流转用
    intimacy: float = 0.0
    trust: float = 0.0
    familiarity: float = 0.0
```

`ConversationState` 扩展（向后兼容，V1 旧路径默认值不炸）：

```python
class ConversationState(BaseModel):
    ...                                    # V1 字段不动
    character_state: CharacterState = CharacterState()
    relationship_state: RelationshipState = RelationshipState()
```

`analysis` 不进 ConversationState（它在 context 构建之后才产生），作为独立参数透传：
`PromptBuilder.build(mode, state, analysis=None)`、`answer_chain.astream(mode, state, analysis, llm)`。

### 3.1 字段归属：LLM 更新 vs 代码控制

| 字段 | 归属 | 理由 |
|---|---|---|
| mood / inner_state / current_topic | **LLM**（`StateUpdateDecision`，后台） | 需要语义判断（「担心用户过度疲劳」无法用规则枚举） |
| energy | **代码** | 规则可控可回放：衰减 + 事件修正 + 闲置恢复 |
| intimacy / trust / familiarity | **代码** | 事件→delta 映射，数值变化可测试、可解释 |
| stage | **代码** | 阈值 + 迟滞带迁移，防抖动，绝不让 LLM 直接改 |

原则：**LLM 负责「理解」，代码负责「数值」**。凡是进数据库的浮点数，一律由确定性规则产生；LLM 只产出枚举与短文本。

---

## 4. State Update Engine（状态更新规则）

### 4.1 更新流程（`services/state_service.apply_and_save`，后处理中调用）

```
输入：预侧快照（CharacterState + RelationshipState）、TurnAnalysis、user_input、ai_reply、llm
 1. StateUpdater LLM → StateUpdateDecision（失败 → None）
 2. apply_idle_recovery   —— 以上次落库 updated_at 为基准的闲置恢复
 3. update_energy         —— 衰减 + 事件 / 行为修正 + clamp
 4. apply_relationship    —— EVENT_DELTAS[event] + BEHAVIOR_DELTAS[behavior] 叠加 + clamp
 5. next_stage            —— 阈值迁移（含迟滞带）
 6. apply_character       —— decision 非 None 时更新 mood / inner_state / current_topic
 7. upsert character_state + relationship_state，append emotion_history
```

`state_engine` 全部为**纯函数**（输入输出全量数据，无 IO 无副作用）。

### 4.2 energy 规则

- 每轮基础衰减：`-energy_turn_decay`（默认 0.05）
- 事件修正：achievement `+0.10`、help_given `+0.05`、setback `-0.05`、complaint `-0.05`、conflict `-0.10`、其余 0
- 行为修正：comfort `-0.05`（共情消耗）、show_concern `-0.03`、其余 0
- clamp：`[energy_min=0.1, 1.0]`
- 闲置恢复：`updated_at` 距今超过 `energy_reset_hours`（12h）→ `energy = max(energy, energy_reset_value=0.85)`，且 mood ∈ {tired, angry} → calm

### 4.3 relationship delta 表（`state_engine` 模块常量）

事件表 `EVENT_DELTAS`：

| event | intimacy | trust | familiarity |
|---|---|---|---|
| achievement（用户达成成就） | +0.04 | — | +0.02 |
| share_goal（用户分享目标 / 心事） | +0.02 | +0.06 | — |
| seek_help（用户向角色求助） | +0.02 | +0.05 | +0.02 |
| help_given（用户帮助 / 陪伴角色） | +0.03 | +0.02 | +0.06 |
| setback（用户受挫） | +0.03 | — | — |
| complaint（用户抱怨） | — | -0.03 | — |
| conflict（冲突 / 争吵） | -0.12 | -0.10 | -0.05 |
| daily（日常闲聊） | — | — | +0.01 |
| farewell（道别） | — | — | — |

行为修正表 `BEHAVIOR_DELTAS`（角色本轮采取的行为也反哺关系）：

| behavior | intimacy | trust | familiarity |
|---|---|---|---|
| comfort / celebrate | +0.02 | — | — |
| encourage | — | +0.01 | — |
| recall_memory | — | +0.02 | +0.03 |
| 其余 | — | — | — |

两表**叠加**后 clamp `[0, 1]`。示例：用户分享目标且角色 recall_memory → trust +0.08、intimacy +0.02、familiarity +0.03。

### 4.4 stage 阈值迁移（迟滞防抖）

| 迁移 | 升级条件（同时满足） |
|---|---|
| stranger → friend | familiarity ≥ 0.35 |
| friend → close_friend | intimacy ≥ 0.55 且 trust ≥ 0.55 |
| close_friend → partner | intimacy ≥ 0.75 且 trust ≥ 0.75 |

降级条件：低于「当前阶段升级阈值 − stage_hysteresis(0.10)」才降级，避免数值在阈值附近抖动导致阶段反复横跳。stage 由 `next_stage(intimacy, trust, familiarity, current_stage)` 纯函数从三维数值**重算**，不由 delta 直接改。

### 4.5 settings 新增

```python
energy_turn_decay: float = 0.05
energy_min: float = 0.1
energy_reset_hours: int = 12
energy_reset_value: float = 0.85
stage_friend_familiarity: float = 0.35
stage_close_intimacy: float = 0.55
stage_close_trust: float = 0.55
stage_partner_intimacy: float = 0.75
stage_partner_trust: float = 0.75
stage_hysteresis: float = 0.10
analysis_recent_messages: int = 6          # Turn Analyzer 可见的最近消息条数
```

---

## 5. 数据库设计（`core/db.py` 追加 3 张 ORM）

风格对齐 V1：CheckConstraint 枚举、`datetime.now()`、无 timezone、无外键到 users 表。lifespan `create_all` 自动建表（只增不改，旧表零影响）。

```sql
-- 角色状态：一用户一行，upsert
CREATE TABLE character_state (
    user_id       TEXT PRIMARY KEY,
    mood          TEXT NOT NULL CHECK(mood IN
                  ('happy','calm','worried','sad','shy','excited','tired','angry')),
    energy        REAL NOT NULL,
    current_topic TEXT NOT NULL DEFAULT '',
    inner_state   TEXT NOT NULL,
    created_at    DATETIME NOT NULL,
    updated_at    DATETIME NOT NULL
);

-- 关系状态：一用户一行，upsert
CREATE TABLE relationship_state (
    user_id      TEXT PRIMARY KEY,
    intimacy     REAL NOT NULL,
    trust        REAL NOT NULL,
    familiarity  REAL NOT NULL,
    stage        TEXT NOT NULL CHECK(stage IN
                 ('stranger','friend','close_friend','partner')),
    created_at   DATETIME NOT NULL,
    updated_at   DATETIME NOT NULL
);

-- 情绪 / 状态变迁历史：追加型观测日志，兼作未来 LangGraph checkpoint 的状态变迁记录
CREATE TABLE emotion_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    user_emotion TEXT NOT NULL,
    event        TEXT NOT NULL,
    behavior     TEXT NOT NULL,
    mood_before  TEXT NOT NULL,
    mood_after   TEXT NOT NULL,
    energy_after REAL NOT NULL,
    stage_after  TEXT NOT NULL,
    created_at   DATETIME NOT NULL
);
CREATE INDEX idx_emotion_history_user ON emotion_history(user_id, created_at);
```

设计说明：

- 一对一状态表以 `user_id` 为 PRIMARY KEY（先例：V1 `conversation_summaries` 以 conversation_id 为主键），upsert 语义天然成立。
- `emotion_history` 每轮追加一行（含降级轮），不存 relationship 三维全量快照，只存 `stage_after`——观测维度够用且不膨胀；需要完整回放时由 `state_engine` 规则 + 历史输入可重算。
- 状态按 **user_id** 维度跨会话存续（与 memories 一致）；mood / energy 不区分 session。

---

## 6. LCEL Chain 设计（保持 V1 轻量风格）

### 6.1 两条新链（与 V1 四条链同构：build-per-call 短链）

```python
# chains/turn_analysis_chain.py —— 预侧：一次结构化输出
prompt 变量：{user_message} {recent_context} {character_snapshot} {relationship_snapshot}
chain = ChatPromptTemplate.from_messages([("system", turn_analysis_prompt)]) \
        | llm.with_structured_output(TurnAnalysis)

# chains/state_update_chain.py —— 后处理：LLM 更新角色内在状态
prompt 变量：{character_snapshot} {relationship_snapshot} {user_emotion} {event}
             {behavior} {user_input} {ai_reply}
chain = ChatPromptTemplate.from_messages([("system", state_update_prompt)]) \
        | llm.with_structured_output(StateUpdateDecision)
```

`turn_analysis_prompt` 要点：枚举取值说明 + 每个行为 1 条少样本示例 + 当前角色 / 关系快照（让行为决策知上下文）+ 最近对话（`analysis_recent_messages` 条）。失败抛异常，由编排层降级。
`state_update_prompt` 要点：给出旧状态，要求输出新 mood（附 mood_reason）、inner_state（一句话）、current_topic（短语）；约束「心情变化要有连续性，不剧烈跳变」。

### 6.2 预侧并发（agent_service.stream_chat 扩展）

```python
role_mode, analysis = await asyncio.gather(
    router_chain.route(content, llm=llm),
    turn_analysis_chain.analyze(content, state, llm=llm),
    return_exceptions=True,
)
# 各自 try/except 降级：role_mode → default；analysis → TurnAnalysis()（neutral/daily/normal_reply）
async for token in answer_chain.astream(mode, state, analysis, llm=llm):
    ...
```

### 6.3 Runnable 组件使用判断（不过度设计）

| 组件 | V2 判断 | 说明 |
|---|---|---|
| `RunnableSequence` | **用（隐式）** | 各链 `prompt \| llm` 管道即隐式序列，保持 V1 build-per-call 风格 |
| `RunnableParallel` | **不用，用 `asyncio.gather`** | 语义上 router ∥ turn_analysis 就是并行分支，但需要**逐任务独立降级**（return_exceptions + 各自 except），服务层是 async 函数风格，gather 更直接 |
| `RunnableLambda` | **不用** | `state_engine` 保持纯函数直接调用，便于单测；包一层 Lambda 无收益 |
| `RunnablePassthrough` | **不用** | 编排用显式局部变量（mode / analysis / state），类型清晰胜过 dict 流 |
| DB 写入（状态落库） | **不用 Runnable** | 延续「读取进链、写入出链」，后处理中执行 |

### 6.4 后处理扩展（`_post_process`，各环节 try/except 隔离）

```
1. state_service.apply_and_save(user_id, session_id, 快照, analysis, user_input, ai_reply, llm)   ← 新增
2. 达阈值 → summary_service.update（V1 不动）
3. memory_service.extract_and_save（V1 不动）
```

状态更新排在摘要 / 记忆之前：状态写入轻量（纯数值 + 短文本），先落保证可观测性。

---

## 7. Prompt 架构升级（PromptBuilder 模块化）

`PromptBuilder.build(mode, state, analysis=None)`，向后兼容（analysis=None 时输出与 V1 完全一致）。最终消息序列：

```
 1. system  IDENTITY_BLOCK                    ┐
 2. system  PERSONALITY_BLOCK                 │ V1 四块不动
 3. system  RELATIONSHIP_BLOCK                │
 4. system  BEHAVIOR_BLOCK                    ┘
 5. system  【角色当前状态】                    ← 新增
 6. system  【与用户的关系】                    ← 新增
 7. system  【用户记忆】                       ┐
 8. system  【对话摘要】                       │ V1 不动
 9. history（human / ai 消息）                 │
10. system  MODE_INSTRUCTIONS[mode]           ┘
11. system  【本轮行为指令】                    ← 新增
12. human   当前输入
```

**section 5 格式**（数值转档位，D2 决策）：

```
【角色当前状态】
心情：worried
精力：一般
最近在聊：用户的 AI Agent 项目
内心：担心用户连续熬夜赶工
```

精力档位：energy ≥ 0.7 → 「充沛」；≥ 0.4 → 「一般」；否则 → 「有些疲惫」。

**section 6 格式**：阶段人设文案（`character/asuna/stages.py` 的 `STAGE_DESCRIPTIONS`，按 SAO 语境撰写四档）+ 三维定性档位（`describe_level`：< 0.3 低 / < 0.5 一般 / < 0.75 深 / ≥ 0.75 很深）：

```
【与用户的关系】
当前关系：好友（你们互相了解、可以聊心里话，但还有些话没说出口）
亲密：一般　信任：深　熟悉：一般
```

**section 11**：`character/asuna/behavior_instructions.py` 的 `BEHAVIOR_INSTRUCTIONS[behavior]`，7 种行为各一段指令（如 comfort：「先接住用户的情绪，表达理解和陪伴，不要急着给建议……」）。`recall_memory` 的指令只引导「自然提起相关记忆」——记忆内容已在 section 7 注入，不重复。

新增角色资产文件与既有 `character/asuna/` 五块并列，PromptBuilder 仍是**唯一组装入口**（AGENTS.md 约束不变）。

---

## 8. 代码目录结构（新增 / 修改标注）

遵循 V1 三层单向依赖（`api → services → repositories → core`），**不采用**「character/ 下放 state / emotion / relationship / behavior 逻辑」的大目录方案——character/ 只放人设资产（V1 既定约定），状态逻辑属业务层。

```
apps/backend/app/
├── character/asuna/
│   ├── behavior_instructions.py        [新] 7 种行为的 prompt 指令片段
│   └── stages.py                       [新] 4 个关系阶段人设文案 + describe_level 档位
│
├── chains/
│   ├── turn_analysis_chain.py          [新] 轮次分析链（TurnAnalysis）
│   ├── state_update_chain.py           [新] 状态更新链（StateUpdateDecision）
│   └── answer_chain.py                 [改] astream 增 analysis 参数
│
├── models/
│   ├── behavior.py                     [新] BehaviorType / BehaviorDecision
│   ├── emotion.py                      [新] UserEmotionLabel / EventCategory / UserEmotion / TurnAnalysis
│   ├── character_state.py              [新] Mood / CharacterState / StateUpdateDecision
│   ├── relationship.py                 [新] RelationshipStage / RelationshipState / RelationshipDelta
│   └── conversation.py                 [改] ConversationState 增两个字段（带默认值）
│
├── core/
│   ├── db.py                           [改] 追加 CharacterStateRow / RelationshipStateRow / EmotionHistoryRow
│   └── settings.py                     [改] 追加状态阈值（见 4.5）
│
├── repositories/
│   ├── character_state_repository.py   [新] get_state（未命中返回默认值）/ upsert_state
│   ├── relationship_repository.py      [新] get_relationship / upsert_relationship
│   └── emotion_history_repository.py   [新] append / list_recent
│
├── services/
│   ├── state_engine.py                 [新] 纯函数规则：闲置恢复 / energy / delta 叠加 / next_stage
│   ├── state_service.py                [新] load_states（context 用）+ apply_and_save（后处理用）
│   ├── context_builder.py              [改] 增读两份状态
│   └── agent_service.py                [改] 预侧 gather 并发 + 双降级；_post_process 增状态落库
│
└── prompts/
    ├── turn_analysis.py                [新] 轮次分析模板
    ├── state_update.py                 [新] 状态更新模板
    └── builder.py                      [改] 新增 3 个 section（见第 7 节）
```

API 层零改动：不新增端点，不改 NDJSON 响应契约（已知前端对错误契约敏感）。

---

## 9. 未来升级 LangGraph 时可直接复用的模块

| 模块 | 复用方式 |
|---|---|
| `services/state_engine.py` | 纯函数，直接作为 Graph 节点或节点内调用，零改动 |
| `models/` 全部 V2 DTO | 可序列化状态对象，直接进 checkpoint state |
| `repositories/` 三个状态仓储 | 原样复用，承接 checkpoint 持久化 |
| `chains/turn_analysis_chain.py`、`chains/state_update_chain.py` | 原样复用为 Graph 节点 |
| `emotion_history` 表 | 天然的状态变迁日志，可回放 / 可审计 |
| `prompts/builder.py` + `character/asuna/` 全部资产 | 原样复用 |
| V1 全部模块 | 按 V1 架构文档第 9 节结论不变 |

需要替换的只有 `agent_service.stream_chat` 的编排（换成节点 / 边）与并发调度的表达方式。V2 与 V1 一样：**编排层最薄、数据与规则模块做厚**。

---

## 10. 明确不做的事

- 不引入 LangGraph、不做 Multi Agent（约束 1 / 2）
- 不改 V1 `memory_service` 及其 repository（约束 3）
- 不改 NDJSON 流式契约、不新增 API 端点（状态观测先靠 emotion_history 表 + 日志）
- 不做向量检索 / 嵌入（V1 P2 backlog 延续）
- 已知 V1 缺陷（孤儿消息、跨用户去重、502 契约细节）不在 V2 范围
- 不做 mood 对回答风格的量化强度控制（如「心情值影响语气参数」），V2 先保证状态注入正确

### V2 P2 Backlog（暂不拆任务）

- 状态调试 API（`GET /api/v1/state`：角色状态 / 关系 / 情绪历史）
- 同一用户并发对话的状态覆盖问题（按 user 加锁或乐观并发）
- mood / energy 的连续时间衰减曲线（当前只有闲置恢复）
- 事件语义细分（如把 conflict 拆出「误会 / 真冲突」）
- 角色主动性行为（基于状态的低概率主动关怀开场）
