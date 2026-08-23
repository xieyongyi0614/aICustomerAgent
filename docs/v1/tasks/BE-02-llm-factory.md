# BE-02 LLM 单例工厂

| 字段 | 内容 |
|---|---|
| Task ID | BE-02 |
| Task Name | LLM 单例工厂 |
| Type | BE |
| Priority | P0 |

## Description

建立 `app/core/llm_factory.py`，提供全局唯一的 `ChatOpenAI` 实例（`get_llm()`），参数全部来自 BE-01 配置。解决 V0 中每次请求新建 LLM 的问题（架构文档 A3），并支持测试注入 mock。

## Scope

- `app/core/llm_factory.py`：
  - `get_llm()`：缓存单例，按 `settings` 组装 `ChatOpenAI`
  - `set_llm(llm)` / `reset_llm()`：测试注入与恢复
- LLM 参数：model、api_key、base_url、temperature、top_p、frequency_penalty、presence_penalty、max_tokens（来自 settings）
- `extra_body={"thinking": {"type": "disabled"}}` 保留 V0 行为

## Out of Scope

- 具体链的构建（BE-06 / BE-08 / BE-09 / BE-12）
- 结构化输出封装（由各链自行 `with_structured_output`）

## Dependencies

- BE-01（settings）

## Input

- V0 `services.py:17-27` 的 LLM 实例化参数
- BE-01 的 `Settings`

## Output

- `app/core/llm_factory.py`

## Business Rules

1. `get_llm()` 多次调用返回**同一实例**。
2. `set_llm(mock)` 后 `get_llm()` 返回 mock，用于测试；`reset_llm()` 清空缓存恢复工厂默认。
3. LLM 实例化惰性：首次调用 `get_llm()` 时才创建。
4. 所有参数透传自 `settings`，工厂内不出现硬编码值。

## API Dependencies

- 无

## Data Dependencies

- 无

## Permission

- 无鉴权要求。

## Error Handling

- API_KEY 缺失：透传 BE-01 的启动报错。
- LLM 构造失败：抛出原异常并包含配置来源信息。

## Subtask 拆分

- S1：实现 `get_llm()` 单例
- S2：实现 `set_llm() / reset_llm()`
- S3：确认与 settings 参数映射
- S4：导入冒烟

## Acceptance Criteria

- 两次 `get_llm()` 为同一对象（`is` 比较）
- `set_llm(fake)` 后 `get_llm()` 返回 fake；`reset_llm()` 后恢复真实工厂
- 实例化参数与 settings 一致（抽查 model / temperature / max_tokens）
- 调用 LLM 时能读到配置的 base_url / api_key

## Test Requirements

- 测试：单例性、set/reset 注入、参数映射。
- 真实网络调用不得出现在测试中（TEST-01 conftest 统一注入 mock）。