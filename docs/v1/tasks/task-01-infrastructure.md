# Task 1 — 基础设施重构

> 前置任务，不引入新功能。修正 V0 硬伤，为记忆层打地基。
> 架构参考：`docs/v1/v1-architecture.md` §8 Task 1

## 目标

- API Key 出源码，进入环境配置
- LLM 单例化，可注入 mock 测试
- 修正路由链模板变量写法
- 巨型 System Message 模块化拆分
- 目录从旧 `modules/llm/` 迁移到三层架构

## 涉及文件

| 操作 | 文件 |
|---|---|
| 新建 | `app/core/settings.py`、`app/core/llm_factory.py` |
| 新建 | `app/chains/router_chain.py` |
| 新建 | `app/character/identity.py`、`personality.py`、`relationship.py`、`behavior.py`、`modes.py` |
| 新建 | `app/prompts/router.py`、`app/prompts/builder.py` |
| 新建 | `app/models/router.py`（迁移 RoleMode） |
| 新建 | `app/services/agent_service.py`、`app/services/__init__.py` |
| 删除 | 旧 `app/modules/llm/`（config.py / models.py / services.py） |
| 删除 | 遗留文件 `app/api/__init__ copy.py` |
| 新建 | `.env` + `.env.example` |

## 实现步骤

1. `core/settings.py`：用 pydantic-settings 管理 `OPENAI_API_KEY / BASE_URL / MODEL / TEMPERATURE / MAX_TOKENS / TOP_P / FREQUENCY_PENALTY / PRESENCE_PENALTY` 等，从 `.env` 读取。
2. `core/llm_factory.py`：`get_llm()` 缓存单例（`lru_cache` 或模块级变量），预留 `set_llm(llm)` 用于测试注入 mock。
3. `chains/router_chain.py`：`ChatPromptTemplate.from_messages([("system", ROLE_ROUTER_PROMPT)]) | llm.with_structured_output(RoleMode)`，模板使用真正的 `{user_message}` 占位符（去掉 `services.py:33` 的手动 `.format`）。
4. 拆分 `ASUNA_CORE`（`config.py:5-56`）为 `character/` 各模块；`MODE_INSTRUCTIONS`（`config.py:59-167`）移入 `character/modes.py`。
5. `prompts/builder.py`：实现分节组装骨架（V1 完整版在 Task 3/4 填充动态段）。
6. 迁移 `RoleMode` 到 `models/router.py`，删除旧 `modules/llm/`。
7. 删除 `app/api/__init__ copy.py`。

## 验收标准

- `grep` 全仓库确认无硬编码 API Key
- `agent_service.py` 承担编排职责，流式功能与 V0 等价
- `pylint` 通过
- `.env.example` 提交，`.env` 进 `.gitignore`