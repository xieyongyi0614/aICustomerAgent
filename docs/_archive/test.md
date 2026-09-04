是，**如果你的目标是学习 LangChain / LangGraph，并最终做成 AI 客服 Agent，我非常推荐用 FastAPI 搭建后端**。

而且你之前本身就计划用 FastAPI 做 Agent，这个组合很合适：

```text
                    Frontend
                       │
                     SSE
                       │
                       ▼
                  ┌─────────┐
                  │ FastAPI │
                  └────┬────┘
                       │
                       ▼
                 ┌───────────┐
                 │ LangGraph │
                 │   Agent   │
                 └─────┬─────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
       LangChain      RAG         Tools
          │            │            │
          ▼            ▼            ▼
         LLM       pgvector      Order API
                                  Refund API
```

我建议你**不要一开始就搭完整企业架构**，先用 1～2 天把最小闭环跑起来。

---

# 一、第一版技术栈

我建议：

| 模块          | 技术                          |
| ------------- | ----------------------------- |
| Web Framework | FastAPI                       |
| Agent         | LangGraph                     |
| AI 基础组件   | LangChain                     |
| LLM           | OpenAI / DeepSeek / Qwen 均可 |
| Database      | PostgreSQL                    |
| Vector        | pgvector                      |
| ORM           | SQLAlchemy                    |
| 配置          | pydantic-settings             |
| Streaming     | SSE                           |
| Package       | uv                            |
| Python        | 3.12+                         |

先**不要**加入：

```text
Redis
Celery
Kafka
Milvus
Elasticsearch
K8s
微服务
```

这些以后再加。

---

# 二、先确定项目目标

第一阶段只做：

> **一个可以对话 + RAG + Tool Calling 的客服 Agent。**

例如：

```text
用户：

你们退款多久到账？

        ↓

FastAPI

        ↓

LangGraph

        ↓

判断：
这是知识库问题

        ↓

pgvector

        ↓

找到：

退款通常需要 3-5 个工作日

        ↓

LLM

        ↓

回答
```

然后：

```text
用户：

帮我查询订单 12345

        ↓

Agent

        ↓

Order Tool

        ↓

查询数据库

        ↓

LLM

        ↓

回答
```

这样就已经是一个真正的 Agent 了。

---

# 三、项目目录

先不要搞得太复杂。

我建议：

```text
ai-customer-agent/
│
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   └── chat.py
│   │
│   ├── agent/
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── nodes/
│   │   │   ├── router.py
│   │   │   ├── rag.py
│   │   │   └── answer.py
│   │   │
│   │   └── tools/
│   │       ├── order.py
│   │       └── refund.py
│   │
│   ├── rag/
│   │   ├── embeddings.py
│   │   ├── vector_store.py
│   │   └── retriever.py
│   │
│   ├── llm/
│   │   └── model.py
│   │
│   ├── db/
│   │   ├── database.py
│   │   └── models.py
│   │
│   └── config.py
│
├── knowledge/
│   ├── refund.md
│   ├── membership.md
│   └── shipping.md
│
├── tests/
│
├── .env
├── pyproject.toml
└── README.md
```

这个结构非常适合学习。

---

# 四、第一步：创建项目

如果你用 `uv`：

```bash
mkdir ai-customer-agent

cd ai-customer-agent

uv init

uv python pin 3.12
```

安装：

```bash
uv add fastapi
uv add "uvicorn[standard]"

uv add langchain
uv add langgraph
uv add langchain-openai

uv add sqlalchemy
uv add psycopg[binary]

uv add pgvector

uv add pydantic-settings
```

如果使用 DeepSeek / Qwen 等兼容 OpenAI API 的模型，也可以通过 LangChain 的 OpenAI-compatible 接口接入。

---

# 五、第二步：先把 FastAPI 跑起来

`app/main.py`

```python
from fastapi import FastAPI

app = FastAPI(
    title="AI Customer Service Agent",
)


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }
```

启动：

```bash
uv run uvicorn app.main:app --reload
```

访问：

```text
http://localhost:8000/docs
```

看到 Swagger 就成功了。

---

# 六、第三步：接 LLM

创建：

```text
app/llm/model.py
```

核心就是：

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="你的模型",
    api_key="你的 API Key",
    base_url="你的 API 地址",
)
```

然后测试：

```python
response = await llm.ainvoke(
    "你是一个电商客服，请介绍一下你的职责"
)

print(response.content)
```

这一步只验证：

```text
FastAPI
   ↓
LangChain
   ↓
LLM
```

先别碰 Agent。

---

# 七、第四步：做第一个 Chain

先做：

```text
Prompt
 ↓
LLM
 ↓
Output
```

例如：

```text
用户问题
    ↓
客服 Prompt
    ↓
LLM
    ↓
客服回答
```

这一步的目的不是做功能。

而是让你理解 LangChain：

```text
ChatPromptTemplate
        ↓
      Model
        ↓
      Parser
```

---

# 八、第五步：加入 RAG

然后开始真正有意思的部分。

先准备：

```text
knowledge/
├── refund.md
├── shipping.md
└── membership.md
```

例如：

```text
# 退款规则

用户申请退款后，平台将在 3-5 个工作日内完成审核。

审核通过后，退款将原路返回。
```

然后：

```text
Markdown
 ↓
Document
 ↓
Chunk
 ↓
Embedding
 ↓
pgvector
```

最终：

```text
用户问题
   ↓
Retriever
   ↓
Top K Documents
   ↓
Prompt
   ↓
LLM
   ↓
回答
```

---

# 九、这里先不要急着上 Agent

非常重要。

先单独把：

```text
RAG
```

跑通。

例如：

```text
POST /chat

{
    "message": "退款多久到账？"
}
```

得到：

```text
根据知识库，退款审核通常需要
3-5 个工作日……
```

如果这个都没跑通，直接上 Agent 会导致你根本不知道问题出在哪里。

---

# 十、第六步：加入 Tool Calling

然后增加：

```python
@tool
def query_order(order_id: str):
    ...
```

例如：

```text
query_order
query_logistics
create_refund
create_ticket
```

于是：

```text
用户
 ↓
LLM
 ↓
需要查询订单？
 ↓
Tool
 ↓
订单数据库
 ↓
Tool Result
 ↓
LLM
 ↓
回答
```

这时候你已经开始真正进入 Agent 开发了。

---

# 十一、第七步：正式引入 LangGraph

这时候再建立：

```text
State
```

例如：

```python
class AgentState(TypedDict):
    messages: list
    intent: str
    documents: list
    tool_result: dict
```

然后：

```text
                Start
                  │
                  ▼
               Router
                  │
          ┌───────┼───────┐
          ▼       ▼       ▼
         RAG     Tool    Human
          │       │
          └───────┘
               │
               ▼
             Answer
               │
               ▼
              End
```

这才是你真正要学习的 LangGraph。

---

# 十二、最终 FastAPI API

第一版只需要三个 API。

### 1. 普通聊天

```text
POST /api/chat
```

---

### 2. SSE 流式聊天

```text
POST /api/chat/stream
```

或者：

```text
GET /api/chat/stream
```

最终：

```text
Frontend
   │
   │ SSE
   ▼
FastAPI
   │
   ▼
LangGraph
   │
   ├── LLM
   ├── RAG
   └── Tools
```

---

### 3. 知识库上传

```text
POST /api/knowledge/upload
```

流程：

```text
上传文件
   ↓
解析
   ↓
Chunk
   ↓
Embedding
   ↓
pgvector
```

---

# 十三、第一阶段甚至可以不用 PostgreSQL

如果你现在最主要的目标是：

> **快速学习 LangChain**

可以再激进一点。

第一版：

```text
FastAPI
+
LangChain
+
LangGraph
+
LLM
+
Chroma
```

直接跑。

结构：

```text
FastAPI
   │
   ▼
LangGraph
   │
   ├── RAG
   │    └── Chroma
   │
   └── Tools
```

等你理解：

```text
Embedding
Retriever
Vector Search
RAG
```

以后再：

```text
Chroma
 ↓
pgvector
```

这样学习曲线会更平滑。

---

# 十四、我反而建议你这样分 4 个版本

## V0.1 —— LLM

目标：

```text
FastAPI
 ↓
LangChain
 ↓
LLM
```

只做聊天。

---

## V0.2 —— RAG

```text
FastAPI
 ↓
LangChain
 ↓
RAG
 ↓
Vector DB
```

实现：

> “根据公司知识库回答问题。”

---

## V0.3 —— Agent

加入：

```text
                 Agent
                   │
          ┌────────┼────────┐
          ▼        ▼        ▼
         RAG      Order    Refund
                  Tool      Tool
```

这时候正式用：

> **LangGraph**

---

## V0.4 —— Production

加入：

```text
                FastAPI
                   │
                   ▼
               LangGraph
                   │
       ┌───────────┼───────────┐
       ▼           ▼           ▼
      RAG         Tools      Guardrail
       │           │           │
       ▼           ▼           ▼
   pgvector    PostgreSQL    Policy
                   │
                   ▼
              Human Handoff
                   │
                   ▼
               Checkpoint
```

再加：

```text
SSE
Redis
PostgreSQL
Observability
Authentication
Rate Limit
```

---

# 十五、你现在最应该做的不是直接写完整项目

我建议你按照：

```text
Day 1
FastAPI + LangChain + LLM

Day 2
Prompt + Structured Output

Day 3
RAG

Day 4
Tool Calling

Day 5
LangGraph

Day 6
Agent Router + 多 Tool

Day 7
SSE + Memory

Day 8+
Human Handoff + Checkpoint
```

这样学习效率会非常高。

---

## 最终你要达到的能力

最终这个项目应该能做到：

```text
用户：
我的订单 12345 到哪里了？

             ↓

        LangGraph Agent

             ↓

        Intent Router

             ↓

       Order Tool

             ↓

        PostgreSQL

             ↓

       Order Result

             ↓

           LLM

             ↓

“你的订单目前已经到杭州转运中心，
预计明天送达。”
```

而如果用户问：

```text
退款多久到账？
```

则：

```text
        LangGraph Agent
                ↓
              Router
                ↓
               RAG
                ↓
             pgvector
                ↓
            Knowledge
                ↓
               LLM
                ↓
             Answer
```

这两个流程跑通以后，你就真正开始理解：

> **LangChain 是 Agent 的能力组件，LangGraph 是 Agent 的流程控制，而 FastAPI 是把整个 Agent 暴露成一个真正可用的后端服务。**

如果按这个项目学，我建议**第一步就从 `FastAPI + LangChain + LLM` 开始，不要先研究 LangGraph**；等你把 Chain、RAG、Tool Calling 跑过一遍，再进入 LangGraph，会非常容易理解。
