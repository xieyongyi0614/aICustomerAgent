# BE-02 状态规则引擎

| 字段 | 内容 |
|---|---|
| Task ID | BE-02 |
| Task Name | state_engine 确定性规则（纯函数） |
| Type | BE |
| Priority | P0 |

## Description

把 V2 全部确定性状态规则收敛到 `app/services/state_engine.py`：energy 衰减与恢复、关系三维 delta 叠加、stage 阈值迁移（含迟滞）。全部纯函数（无 IO、无副作用），数值变化可测试、可回放，是"代码负责数值"原则（架构文档 §3.1）的唯一实现地。

## Scope

- 模块常量：`EVENT_DELTAS`、`BEHAVIOR_DELTAS`（架构文档 §4.3 两表完整落地）、energy 事件修正映射、energy 行为修正映射
- `apply_idle_recovery(state, now) -> CharacterState`：超过 `energy_reset_hours` → `energy = max(energy, energy_reset_value)`，mood ∈ {tired, angry} → calm
- `update_energy(state, analysis) -> float`：`-energy_turn_decay` + 事件 / 行为修正 + clamp `[energy_min, 1.0]`
- `relationship_deltas(event, behavior) -> RelationshipDelta`：两表叠加
- `apply_relationship(rel, event, behavior) -> RelationshipState`：叠加 + clamp `[0, 1]`
- `next_stage(intimacy, trust, familiarity, current_stage) -> RelationshipStage`：阈值升级 + 迟滞降级
- `apply_character(state, decision, analysis) -> CharacterState`：decision 非 None 时更新 mood / inner_state / current_topic，为 None 时三者保持；energy 恒用 `update_energy` 结果
- `app/core/settings.py` 追加架构文档 §4.5 全部阈值

## Out of Scope

- LLM 决策获取（BE-04）
- 落库编排（BE-07 的 `state_service.apply_and_save`）
- 闲置恢复的"基准时间"来源（由调用方传入）

## Dependencies

- BE-01（DTO）
- DB-01（settings 无依赖，但同队列基础串）

## Input

- `docs/version/v1.0.0/v2/v2-architecture.md` §4 State Update Engine

## Output

- `app/services/state_engine.py`
- `app/core/settings.py`（修改）
- `tests/test_state_engine.py`

## Business Rules

1. 阈值（衰减量、恢复时长、stage 阈值、迟滞带）一律读 `get_settings()`；delta 映射表留模块常量（架构文档 D3 决策）。
2. 事件与行为 delta **叠加**后生效（例：share_goal + recall_memory → trust +0.08、intimacy +0.02、familiarity +0.03）。
3. stage 由 `next_stage` 从三维数值**重算**，不由 delta 直接改；降级需低于「升级阈值 − stage_hysteresis」。
4. 浮点结果一律 clamp，绝不下穿 `energy_min` / 负数、不上穿 1.0。
5. `apply_character` 中 mood / inner_state / current_topic 只信 `StateUpdateDecision`，LLM 失败（decision=None）时保持旧值。

## API Dependencies

- 无

## Data Dependencies

- 无（纯函数，输入输出全量数据）

## Permission

- 无

## Error Handling

- 未知 event / behavior 组合查表 miss → 按 0 delta 处理，不抛错（防御未来枚举扩展不同步）。

## Subtask 拆分

- S1：settings 阈值 + delta 常量表
- S2：energy（衰减 / 修正 / clamp / 闲置恢复）
- S3：relationship 叠加 + next_stage 迟滞
- S4：apply_character 组装
- S5：全规则单测

## Acceptance Criteria

- energy clamp 双边界（0.1 与 1.0）正确
- achievement + recall_memory 叠加 delta 精确等于两表之和
- friend → close_friend 升级触发；数值回落但在迟滞带内不降级；跌破阈值 −0.10 才降级
- 闲置 13h：energy 恢复至 0.85、tired → calm；闲置 1h 不触发
- decision=None 时 mood / inner_state / current_topic 不变、energy 照常衰减

## Test Requirements

- `tests/test_state_engine.py`：纯函数直测（无需 DB / LLM / monkeypatch）
- 覆盖每个 delta 表条目至少一次 + 叠加组合 + clamp + 迟滞三态
