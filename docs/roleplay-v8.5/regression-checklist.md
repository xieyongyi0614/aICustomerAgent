# V8.5 Relationship Evolution 回归清单（人工真实模型）

> 前置：`apps/backend` 单命令全量测试全绿（`python -m pytest tests -q --basetemp=.pytest_tmp`）。
> 全局底线：默认态下 prompt 字节（golden）、V5 行为、V7 policy 输出三者不变。

## 一、开关矩阵

| 开关 | 默认 | 关闭后预期 |
|---|---|---|
| `REL_EVOLUTION_ENABLED` | true | 演化引擎关闭，行为与 V5 逐位一致（黄金测试通过） |
| `REL_SIGNAL_LLM_ENABLED` | false | 信号仅通道 A（词表），无新增 LLM 调用 |
| `REL_MILESTONE_ENABLED` | true | 关闭后不检测/不刻印/不加 bonus |
| `REL_CONFLICT_ENABLED` | true | 关闭后无冲突状态机迁移 |
| `REL_TENSION_FREEZE` | 0.5 | tension 冻结线（默认态渲染不变） |
| `REL_SNAPSHOT_KEEP` | 20 | 快照限频保留窗口 |

## 二、自动化覆盖（已常驻）

- 状态/引擎：`tests/unit/test_relationship_model.py`、`test_evolution_engine.py`、`test_evaluation_relationship.py`
- 信号：`tests/unit/test_interaction_signal.py`、`test_signal_lexicon.py`
- 编年史/冲突/记忆/回放：`tests/v8.5/`（milestone / conflict / memory / replay）
- 行为与自主：`tests/v8.5/test_relationship_context.py`（B1~B5）、`test_relationship_autonomy.py`（R1~R5）
- 仓储与端点：`tests/integration/test_relationship_{snapshots,milestone_repo,conflict_repo}.py`、`tests/e2e/test_debug_relationship.py`
- 长期场景 + 性能：`tests/v8.5/test_relationship_scenarios.py`

## 三、真实模型演练（五条）

1. **正向升温**：连续 3~5 轮真诚分享 → 预期 trust/intimacy 缓慢上升（单轮 ≤0.15），无跳变；`/debug/relationship/state` 观察 version 与维度。
2. **首次袒露**：用户首次倾诉压力 → 预期刻印 `first_self_disclosure`（memory_worthy，进 V4 记忆，importance 0.80）。
3. **冲突全周期**：连续负面表达 → strain/conflict；道歉 → recovery；两轮正向 → resolved；期间自主行为被 R1 克制。
4. **疏远→召回**：>stage 阈值天数不联系 → neglect_active；召回消息（R5）后恢复；重逢后 neglect 复位。
5. **异常护栏**：观察 V7.5 Relationship Evaluation——人为注入异常（如首轮 trust≈1）应报 `relationship_jump`（severity high）。

## 四、Prompt 抽查

- 默认态（维度处于中带、无里程碑/冲突/neglect）关系段落与 V5 快照逐字节一致。
- 冲突期出现冲突指令行；neglect 出现回归注记；新里程碑出现"最近的一个里程碑"行（均受字数预算约束）。

## 五、回滚演练

1. 产生 ≥3 个版本后，`POST /api/v1/debug/relationship/rollback?target_version=1`。
2. 预期：返回 `final_state` = 关键帧 + 其后账本重放；自动留 `manual_pre_rollback` 快照，可审计、幂等。
3. `GET /api/v1/debug/relationship/timeline` 能看到 event/milestone/conflict/snapshot 四类混合倒序时间线。

## 六、通过标准

- 自动化全绿 + golden 零重生成 + 三底线不变。
- 五条演练行为与上述预期一致，无关系分数异常跳变。
