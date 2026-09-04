# BE-14 路由低置信度降级

| 字段 | 内容 |
|---|---|
| Task ID | BE-14 |
| Task Name | 路由低置信度降级 |
| Type | BE |
| Priority | P1 |

## Description

消费 `RoleMode.confidence` 字段（V0 架构问题 A10）：当路由结果 confidence 低于阈值时，将模式降级为 `default`，避免误判导致角色表现失当。同时决定 `intent` 字段的消费策略（可暂时仅透传或后续用于行为调节）。

## Scope

- 在 BE-06 `route()` 之后（或 BE-13 编排层）增加降级逻辑：
  - `confidence < settings.ROUTER_CONFIDENCE_THRESHOLD`（建议 0.5）→ mode 强制 `default`
- `settings.py` 增加 `ROUTER_CONFIDENCE_THRESHOLD`
- intent 字段：当前仅随 RoleMode 透传，留作后续 Prompt 微调（不做行为分支）

## Out of Scope

- 重新路由重试
- intent 驱动的 Prompt 行为分支（后续版本）

## Dependencies

- BE-06（router_chain）
- BE-01（settings 扩展）
- BE-13（编排接入点）

## Input

- `app/chains/router_chain.py`、`app/services/agent_service.py`
- `settings.ROUTER_CONFIDENCE_THRESHOLD`

## Output

- 降级逻辑（位于 router_chain 或 agent_service）
- `settings.py` 新配置项

## Business Rules

1. 降级仅作用于 mode，不影响 intent / reason 透传。
2. 阈值可配置，默认 0.5。
3. 降级日志记录原因（reason），便于调试。

## API Dependencies

- 无

## Data Dependencies

- 无

## Permission

- 无鉴权要求。

## Error Handling

- 无新增异常路径；纯判断逻辑。

## Subtask 拆分

- S1：settings 增加阈值
- S2：降级逻辑实现
- S3：接入 BE-13 编排

## Acceptance Criteria

- mock `confidence=0.3` → 最终 mode 为 default
- mock `confidence=0.8` → 保持原 mode
- 降级时日志含 reason

## Test Requirements

- 低/高置信度两分支测试。
- 确认不影响回答链输入合法性。