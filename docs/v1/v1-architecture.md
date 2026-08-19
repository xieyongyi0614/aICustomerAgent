# V1 角色对话 Agent 架构设计（三层架构）

> 目标：让「亚丝娜」角色从单轮问答升级为具备记忆能力的角色 Agent。
> 分层方式：Controller / Service / Repository 三层架构。

---

## 1. 当前 V0 架构问题分析

### 1.1 架构级问题

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| A1 | **完全无状态**：每个请求都是单轮，Human/AI 消息不落库 | `chat.py:8` → `services.py:53` | 无法多轮，V1 核心目标不满足 |
| A2 | **无 session/user 概念**：API 没有 session_id，无法区分对话 | `chat.py:7-9` | 记忆无归属载体 |
| A3 | **LLM 在函数内新建**：每次请求重新 `ChatOpenAI(...)` | `services.py:17-27` | 无法复用、无法测试、无法注入依赖 |
| A4 | **API Key / base_url / model 硬编码在源码** | `services.py:19-21` | 泄漏风险，无法多环境切换 |
| A5 | **流式输出打到控制台**，端点不返回任何数据 | `services.py:53-57` | 前端完全无法消费 |
| A6 | **无错误处理**：异常只 `print` | `services.py:64-65` | API 层没有可用的错误响应 |

### 1.2 代码级问题

- **A7 模板变量失效**：`role_router_prompt.format(user_message=content)` 在 `services.py:33` 已手动格式化，随后 `ChatPromptTemplate` 内已无占位符，`invoke({"user_message": content})` 传入的变量实际是空操作，两条路径冗余且语义混乱。
- **A8 巨型 System Message**：`ASUNA_CORE + MODE_INSTRUCTIONS[mode]`（`config.py:175`）单字符串拼接，记忆/摘要/历史无从注入，也没有模块边界。
- **A9 单一函数职责过载**：`llm_chat_open_ai` 同时做路由、prompt 构建、回答、流式、计时、日志。
- **A10 计算字段未使用**：`RoleMode.intent / confidence` 被生成但从不消费（`models.py:6-9`）；`confidence` 低时无降级逻辑。
- **A11 `max_tokens=50` 过短**：专业回答易被截断。
- **A12 无类型化消息流**：无法区分 HumanMessage/AIMessage，为记忆层铺垫为零。
- **A13 遗留文件** `app/api/__init__ copy.py`；无测试。

---

## 2. 三层架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1  表现层（Controller / API）                                │
│   api/v1/chat.py       接收 session_id + user_input，流式返回        │
└──────────────────────────────┬───────────────────────────────────┘
                               ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 2  业务逻辑层（Service）                                     │
│   agent_service        主编排：router→memory→context→answer→post   │
│   role_router          路由（chains/router_chain.py）              │
│   conversation_service 短期记忆：读写窗口                           │
│   summary_service      摘要：触发阈值 + 滚动压缩                    │
│   memory_service       长期记忆：提取 / 检索 / 去重                 │
│   context_builder      Context 组装（Memory+Summary+History+Input）│
│   + chains/            LangChain 链定义                            │
└──────────────────────────────┬───────────────────────────────────┘
                               ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 3  数据访问层（Repository）                                  │
│   conversation_repository   会话 / 消息（短期记忆）                 │
│   summary_repository        对话摘要                               │
│   memory_repository         长期记忆                               │
└──────────────────────────────┬───────────────────────────────────┘
                               ↓
                          SQLite（core/db.py）
```

**支撑层（非三层职责，被三层共享引用）**：

```
core/        基础设施：settings（配置）、llm_factory（LLM 单例）、db（SQLite 引擎）
models/      Pydantic 数据模型（跨层流通的 DTO）
prompts/     Prompt 模板 + PromptBuilder（模块化组装）
character/   角色资产：身份 / 人格 / 关系 / 行为 / 模式
```

---

## 3. 三层架构数据流

```
用户输入 + session_id
   ↓
[Layer 1] api/v1/chat.py          —— 参数校验、新建会话、流式响应返回
   ↓
[Layer 2] agent_service.py        —— 编排：
   ├── chains/router_chain.py         → RoleMode（Pydantic Structured Output）
   ├── conversation_service           → 加载最近 N 条消息（短期记忆）
   ├── summary_service                → 读取摘要
   ├── memory_service                 → 检索相关长期记忆
   ├── context_builder                → 组装 System + Memory + Summary + Recent + Input
   ├── answer_chain（PromptBuilder | LLM）→ 流式输出
   └── 流结束后 post-process：
        ├── 保存 Human/AI 消息（conversation_service）
        ├── 达阈值触发摘要更新（summary_service）
        └── 记忆提取（memory_service + chains/extractor_chain.py）
   ↓
[Layer 3] repositories + SQLite    —— 持久化
```

**关键决策**：
- 读取进链、写入出链：DB 读取（load_context）在生成前完成；DB 写入（存消息 / 存记忆 / 更新摘要）在流式结束后由 Service 层执行，避免副作用污染 `stream()`、避免写入失败拖垮对话。
- 依赖方向单向：`api → services → repositories → core`，`models / prompts / character` 为跨层共享 DTO 与资产，禁止反向引用。

---

## 4. 文件目录结构

```
apps/backend/app/
├── __init__.py
│
├── core/                        # 基础设施（支撑层）
│   ├── __init__.py
│   ├── settings.py              # pydantic-settings：API Key / base_url / 模型名 / 阈值
│   ├── llm_factory.py           # LLM 单例工厂（可注入 mock 测试）
│   └── db.py                    # SQLite 引擎 / 会话管理（建表统一入口）
│
├── api/                         # ── Layer 1：表现层 ──
│   ├── __init__.py
│   └── v1/
│       ├── __init__.py
│       ├── router.py            # APIRouter 汇总
│       ├── schemas.py           # 请求 / 响应 DTO（session_id、流式消息体）
│       └── chat.py              # 聊天端点
│
├── services/                    # ── Layer 2：业务逻辑层 ──
│   ├── __init__.py
│   ├── agent_service.py         # 主编排：router→memory→context→answer→post-process
│   ├── context_builder.py       # Context Builder：组装完整 Prompt 输入
│   ├── conversation_service.py  # 短期记忆：加载 / 保存 / 窗口裁剪
│   ├── summary_service.py       # 摘要：阈值触发 / 滚动压缩
│   └── memory_service.py        # 长期记忆：提取 / 检索 / 去重 / 落库
│
├── chains/                      # LangChain 链定义（业务逻辑层的 AI 部分）
│   ├── __init__.py
│   ├── router_chain.py          # 路由链：ChatPromptTemplate | with_structured_output(RoleMode)
│   ├── answer_chain.py          # 回答链构建器：按 mode+context 动态组装
│   ├── summary_chain.py         # 摘要链：滚动压缩（old_summary + new_messages）
│   └── extractor_chain.py       # 记忆提取链：with_structured_output(MemoryDecision)
│
├── repositories/                # ── Layer 3：数据访问层 ──
│   ├── __init__.py
│   ├── conversation_repository.py   # conversations / messages CRUD
│   ├── summary_repository.py        # conversation_summaries CRUD
│   └── memory_repository.py         # memories CRUD（未来换 Vector 只改这一层）
│
├── models/                      # Pydantic 模型（支撑层）
│   ├── __init__.py
│   ├── router.py                # RoleMode
│   ├── conversation.py          # ChatMessage / ConversationState
│   ├── summary.py               # ConversationSummary
│   └── memory.py                # MemoryDecision / UserMemory / MemoryType
│
├── prompts/                     # Prompt 模板 + Builder（支撑层）
│   ├── __init__.py
│   ├── router.py                # 路由模板
│   ├── summary.py               # 摘要模板
│   ├── extractor.py             # 提取模板
│   └── builder.py               # PromptBuilder：分节组装，不拼接巨型字符串
│
└── character/                   # 角色资产（支撑层）
    ├── __init__.py
    ├── identity.py              # 亚丝娜核心人格（拆分自 ASUNA_CORE）
    ├── personality.py           # 人格细化
    ├── relationship.py          # 与用户的关系设定
    ├── behavior.py              # 行为原则
    └── modes.py                 # 三档模式指令（迁移自 MODE_INSTRUCTIONS）
```

> 注：旧 `modules/llm/`（config.py / models.py / services.py）按上表拆分迁移后废弃删除。

---

## 5. 数据库设计（SQLite，SQLAlchemy 2.0）

为未来 Vector DB 预留：所有 memory 读写只走 `memory_repository` 接口，换存储不影响上层。

```sql
-- 会话表：短期记忆与摘要的归属
CREATE TABLE conversations (
    id           TEXT PRIMARY KEY,        -- session_id
    user_id      TEXT NOT NULL,
    created_at   DATETIME NOT NULL,
    updated_at   DATETIME NOT NULL
);

-- 消息表：短期记忆（V1 全量落库，窗口裁剪只在"读取"时做）
CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL CHECK(role IN ('human','ai')),
    content         TEXT NOT NULL,
    created_at      DATETIME NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);
CREATE INDEX idx_messages_conv ON messages(conversation_id, created_at);

-- 摘要表：一对话一行，滚动更新
CREATE TABLE conversation_summaries (
    conversation_id TEXT PRIMARY KEY,
    summary         TEXT NOT NULL,
    created_at      DATETIME NOT NULL,
    updated_at      DATETIME NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);

-- 长期记忆表：未来可加 embedding BLOB + vector 索引列
CREATE TABLE memories (
    id          TEXT PRIMARY KEY,          -- uuid
    user_id     TEXT NOT NULL,
    memory      TEXT NOT NULL,
    memory_type TEXT NOT NULL CHECK(memory_type IN
                 ('preference','fact','goal','experience','relationship')),
    importance  REAL NOT NULL DEFAULT 0.5,
    created_at  DATETIME NOT NULL,
    updated_at  DATETIME NOT NULL
);
CREATE INDEX idx_memories_user ON memories(user_id);
```

---

## 6. Pydantic Model 设计

```python
# models/router.py
class RoleMode(BaseModel):
    mode: Literal["professional", "default", "immersive"]
    intent: Literal["technical", "casual", "emotional", "roleplay", "sao_lore"]
    confidence: float          # V1：低 confidence 时降级到 default
    reason: str

# models/conversation.py
class ChatMessage(BaseModel):
    role: Literal["human", "ai"]
    content: str

class ConversationState(BaseModel):          # Context Builder 的输入/输出载体
    session_id: str
    user_id: str
    messages: list[ChatMessage]              # 窗口内最近消息
    summary: str | None
    memories: list["UserMemory"]             # 检索到的长期记忆
    current_input: str

# models/summary.py
class ConversationSummary(BaseModel):
    conversation_id: str
    summary: str
    updated_at: datetime

# models/memory.py
class MemoryDecision(BaseModel):             # Memory Extractor 输出
    should_save: bool
    memory: str | None
    memory_type: Literal["preference", "fact", "goal", "experience", "relationship"]
    importance: float                        # 0.0 ~ 1.0

class UserMemory(BaseModel):
    id: str
    user_id: str
    memory: str
    memory_type: Literal["preference", "fact", "goal", "experience", "relationship"]
    importance: float
    created_at: datetime
    updated_at: datetime
```

---

## 7. LangChain Chain 设计

### 7.1 三条结构化输出 / 生成链

```python
# chains/router_chain.py：路由链（修正 A7，用真正的模板变量）
router_chain = ChatPromptTemplate.from_messages([("system", ROLE_ROUTER_PROMPT)])
              | llm.with_structured_output(RoleMode)

# chains/summary_chain.py：摘要链（滚动压缩 old_summary + new_messages → new_summary）
summary_chain = ChatPromptTemplate.from_messages([("system", SUMMARY_PROMPT)]) | llm

# chains/extractor_chain.py：记忆提取链
extractor_chain = ChatPromptTemplate.from_messages([("system", EXTRACTOR_PROMPT)])
                 | llm.with_structured_output(MemoryDecision)
```

### 7.2 主 Agent 流水线（哪里用 Runnable 组件）

```python
agent_pipeline = (
    RunnablePassthrough()                                  # 承载 {user_input, session_id}
    | RunnableLambda(load_context)                         # Memory Layer：读历史+摘要+长期记忆
    | RunnablePassthrough.assign(role_mode=router_chain)   # 路由结果挂载到 state
    | RunnableLambda(PromptBuilder.build)                  # 模块化组装 ChatPromptTemplate
    | llm                                                   # 流式
)
```

| Runnable 组件 | 用途 | 判断 |
|---|---|---|
| `RunnablePassthrough` | 在 state 字典上"追加字段"，避免手写 state 传递 | **用**——符合"state 流"语义 |
| `RunnableLambda(load_context)` | 包装 DB 读取这类有副作用但必须在链内的逻辑 | **用**——让整条流水线统一 `astream()/ainvoke()` 接口 |
| `RunnablePassthrough.assign(router_chain)` | 把结构化输出结果挂到 state | **用**——比手动两次 invoke 干净 |
| DB **写入**（存消息、存记忆、更新摘要） | 属于生成后的副作用 | **不用 Runnable**——放在 Service 层，流结束后执行，避免写入失败拖垮对话 |

结论：**读取进链、写入出链**。不要将提取记忆 / 存消息 / 摘要更新塞进 `agent_pipeline`。

### 7.3 Service 层执行流程（agent_service.py）

```
1. load_context(session_id, user_input)        # 读最近 N 条 + summary + 检索 memories
2. role_mode = await router_chain.ainvoke(...)
3. 组装 prompt → async for chunk in agent_pipeline.astream(...)   # 返回给前端
4. 流结束后：
   a. 保存 HumanMessage + AIMessage（内容在流式时累计）
   b. 消息数达阈值 → 触发 summary_chain 滚动更新
   c. 运行 extractor_chain → should_save & importance ≥ 0.6 → 入库（带去重检查）
```

---

## 8. 开发任务拆分（按顺序，每步可独立验收）

### Task 1 — 基础设施重构（不引入新功能）

- **目标**：修正 V0 硬伤，为记忆层打地基；API Key 出源码、LLM 单例化、模板写法修正、Prompt 模块化。
- **涉及文件**：新建 `core/settings.py`、`core/llm_factory.py`、`chains/router_chain.py`、`character/`（identity/personality/relationship/behavior/modes）、`prompts/`（router/builder）、`models/router.py`；删除旧 `modules/llm/`。
- **实现步骤**：
  1. `core/settings.py`：用 pydantic-settings 管理 `OPENAI_API_KEY / BASE_URL / MODEL / TEMPERATURE / MAX_TOKENS` 等，支持 `.env`。
  2. `core/llm_factory.py`：`get_llm()` 缓存单例，支持测试注入。
  3. 新建 `chains/router_chain.py`，修正模板变量（去掉手动 `.format`）。
  4. 拆分 `ASUNA_CORE` 到 `character/`，`MODE_INSTRUCTIONS` 移入 `character/modes.py`；写 `prompts/builder.py` 分节组装。
  5. 删除遗留文件 `app/api/__init__ copy.py` 与旧 `modules/llm/`。
- **验收标准**：无硬编码密钥（grep 确认）；`agent_service.py` 承担编排；流式功能与 V0 等价；`pylint` 通过。

### Task 2 — 短期记忆（多轮上下文）

- **目标**：实现"第二轮知道第一轮"。
- **涉及文件**：`core/db.py`；新建 `repositories/conversation_repository.py`、`services/conversation_service.py`、`models/conversation.py`；改 `api/v1/chat.py`、`api/v1/schemas.py`。
- **实现步骤**：
  1. `core/db.py`：SQLite engine + SQLAlchemy ORM 建表（conversations / messages）。
  2. `repositories/conversation_repository.py`：`save_message / get_recent_messages(conv_id, limit)`。
  3. `services/conversation_service.py`：`load_window(conv_id)` 返回 `list[ChatMessage]`，实现"最近 N 条 + 最大字符预算裁剪"策略（读取时裁剪，不改库）。
  4. `api/v1/chat.py`：端点接收 `session_id`（不存在则新建 conversation）；流式输出改为 HTTP 流式响应返回。
  5. `agent_service.py`：流结束后保存 Human+AI 消息。
- **验收标准**：同一 session_id 下，"我在学 LangGraph" → "我今天刚学 Runnable" 第二轮回答能引用第一轮；不同 session_id 互不可见。

### Task 3 — 对话摘要（长期聊天不爆窗）

- **目标**：超过阈值后触发滚动摘要，prompt 中注入 summary。
- **涉及文件**：`repositories/summary_repository.py`、`services/summary_service.py`、`chains/summary_chain.py`、`prompts/summary.py`、`models/summary.py`；改 `services/conversation_service.py`、`prompts/builder.py`。
- **实现步骤**：
  1. `core/db.py` 增加 `conversation_summaries` 表；`models/summary.py` 定义 `ConversationSummary`。
  2. `chains/summary_chain.py` + `prompts/summary.py`：滚动压缩 prompt（old_summary + new_messages → new_summary）。
  3. `services/summary_service.py`：消息数 > 阈值（如 40 条 = 20 轮）→ 生成/更新摘要。
  4. `prompts/builder.py` 增加 Summary 段；`context_builder.py` 将 summary 组装进 state。
- **验收标准**：20 轮后触发摘要生成；摘要正确概括早期内容；超长对话的 prompt 长度受控（不随轮数无限增长）。

### Task 4 — 长期记忆提取 + 存储 + 检索

- **目标**：只保存值得记住的信息，并能在后续对话中召回。
- **涉及文件**：`models/memory.py`、`chains/extractor_chain.py`、`prompts/extractor.py`、`repositories/memory_repository.py`、`services/memory_service.py`；改 `prompts/builder.py`、`agent_service.py`。
- **实现步骤**：
  1. `models/memory.py`：`MemoryDecision / UserMemory / MemoryType`。
  2. `chains/extractor_chain.py`：输入用户消息 + AI 回复，输出 `MemoryDecision`。
  3. `repositories/memory_repository.py`：`create_memory / list_by_user / 去重检查`。
  4. `services/memory_service.py`：`retrieve(user_id, user_input)` V1 用关键词匹配（词重叠度打分，返回 top-K 且 ≥ 阈值）；接口签名对齐未来向量检索。
  5. `prompts/builder.py` 注入 User Memory 段。
- **验收标准**："我喜欢日本料理，尤其是寿司" → 保存为 preference；"今天吃了拉面" → `should_save=false` 不落库；后续"我想吃点什么"能带出寿司偏好。

### Task 5 — 完整编排 + 端到端

- **目标**：Context Builder 完整拼装 + LCEL 流水线 + 流式返回 + 错误处理。
- **涉及文件**：新建 `services/context_builder.py`、`chains/answer_chain.py`；改 `agent_service.py`、`api/v1/chat.py`。
- **实现步骤**：
  1. `services/context_builder.py`：组装 `ConversationState`（memory + summary + recent + input）。
  2. `chains/answer_chain.py`：`PromptBuilder.build(mode, state) | llm`，实现 7.2 的 `agent_pipeline`。
  3. `api/v1/chat.py`：session_id 校验、流式分块响应、异常转 HTTP 500 + 日志。
  4. 全链路串联 Task 1-4。
- **验收标准**：一条完整请求 = 路由 → 记忆 → 上下文 → 流式回答 → 存消息 → 摘要 → 记忆提取，全部串通；无 session 时自动新建。

### Task 6 — 测试

- **目标**：核心模块可测。
- **涉及文件**：`tests/` 下 `test_retrieval.py`、`test_summary.py`、`test_extractor.py`、`test_memory.py`、`test_conversation.py`。
- **实现步骤**：LLM 用 mock 注入（`llm_factory` 支持替换）；DB 用内存 SQLite；覆盖：窗口裁剪、摘要触发、提取过滤（`should_save` 分支）、检索 top-K、多轮上下文。
- **验收标准**：`pytest` 全绿；`pylint` 通过。

---

## 9. 未来升级 LangGraph 时可直接复用的模块

| 模块 | 复用方式 |
|---|---|
| `chains/extractor_chain.py`、`repositories/memory_repository.py`、`services/memory_service.py` | 原样复用，成为 Graph 的节点或 Tool |
| `services/summary_service.py` + `chains/summary_chain.py` | 原样复用，作为 "condense" 节点 |
| `repositories/conversation_repository.py`、`services/conversation_service.py` | 原样复用，承载短期状态（替代或配合 checkpointer） |
| `character/*`（identity/personality/relationship/behavior/modes） | 纯数据定义，原样复用 |
| `prompts/builder.py` | 原样复用，Graph 节点内调用即可 |
| `services/context_builder.py` | 复用作"组装 state 的节点" |
| `core/`（settings / db / llm_factory） | 原样复用 |

需要替换的只有 `services/agent_service.py` 的 LCEL 流水线编排（换成 graph 的节点 / 边）与 `chains/answer_chain.py` 的调用方式。V1 刻意让编排层保持最薄，数据与业务模块做厚——这是为 LangGraph 留好的替换点。