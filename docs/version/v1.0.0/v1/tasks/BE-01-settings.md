# BE-01 环境配置模块

| 字段 | 内容 |
|---|---|
| Task ID | BE-01 |
| Task Name | 环境配置模块（pydantic-settings） |
| Type | BE |
| Priority | P0 |

## Description

建立 `app/core/settings.py`，用 pydantic-settings 管理全部运行配置，从 `.env` 读取。解决 V0 中 API Key / base_url / model 硬编码问题（架构文档 A4）。

## Scope

- `app/core/settings.py`：`Settings` 模型（BaseSettings）
- 配置项：`OPENAI_API_KEY`、`BASE_URL`、`MODEL`、`TEMPERATURE`、`TOP_P`、`FREQUENCY_PENALTY`、`PRESENCE_PENALTY`、`MAX_TOKENS`、`DATABASE_URL`、`SUMMARY_THRESHOLD`（默认 40）、`MEMORY_IMPORTANCE_THRESHOLD`（默认 0.6）、`MEMORY_TOP_K`（默认 5）、`CONVERSATION_MAX_MESSAGES`（默认 20）、`CONVERSATION_MAX_CHARS`（默认 8000）
- 提供 `.env.example` 模板；`.env` 加入 `.gitignore`
- 全局单例 `get_settings()`

## Out of Scope

- LLM 实例创建（BE-02）
- 业务逻辑

## Dependencies

- ARCH-01

## Input

- V0 `services.py:17-27` 中硬编码的 LLM 参数
- `docs/version/v1.0.0/v1/v1-architecture.md` §8 Task 1、Task 3/4 的阈值设定

## Output

- `app/core/settings.py`
- `.env.example`
- `.gitignore` 增加 `.env`

## Business Rules

1. 敏感项（API_KEY）必须只从环境变量/.env 读取，源码与文档零硬编码。
2. 所有 LLM 参数提供默认值，未配置时不崩溃（API_KEY 除外，缺失时启动即报错）。
3. 阈值类配置集中在此，业务层禁止硬编码魔法数字。
4. 提供 `get_settings()` 单例（`lru_cache`）。

## API Dependencies

- 无

## Data Dependencies

- 无

## Permission

- 无鉴权要求。

## Error Handling

- `OPENAI_API_KEY` 缺失：`SettingsError` 明确提示"请在 .env 配置 OPENAI_API_KEY"。
- 非法枚举/类型：pydantic 原生 `ValidationError` 保留，不吞异常。

## Subtask 拆分

- S1：确认 `pydantic-settings` 依赖
- S2：定义 `Settings` 模型与全部配置项
- S3：`get_settings()` 单例
- S4：`.env.example` 模板 + `.gitignore`
- S5：导入冒烟

## Acceptance Criteria

- `.env` 设置 `OPENAI_API_KEY=test` 后，`get_settings().openai_api_key == "test"`
- 未设置时，缺失 API_KEY 抛出明确错误
- 全部阈值默认值符合架构文档（40 / 0.6 / 5 / 20 / 8000）
- grep 全仓确认无硬编码密钥

## Test Requirements

- 用 `monkeypatch`/`env` 覆盖验证配置加载与默认值。
- 缺失 API_KEY 报错路径测试。