# V8.5 Testing（测试设计）

> 全部确定性（禁真实 LLM，FakeLLM 夹具）、全部可并行（xdist loadscope，每测试独立内存 DB）、全量既有 1069+ 零回归是每个 Task 的底线。

## 1. 测试分层

| 层 | 内容 | 位置 |
|---|---|---|
| 单元 | 五组域模型、映射矩阵、动力学修饰器、限速、阶段兼容、里程碑谓词、冲突迁移矩阵、neglect/张力消退、记忆候选、派生指标、档位文案 | tests/unit/ |
| 集成 | post_process 第 2 步演化流水线、同事务账本对账、三新表仓储与迁移、回滚、评估规则全链、policy 快照装配 | tests/integration/ |
| 场景 | 长期演化模拟（30 天累计、冲突全生命周期、疏远→召回）、黄金不变量、性能护栏 | tests/v8.5/ |
| E2E | /debug/relationship 三端点、时间线 | tests/e2e/ |
| 回归 | V1~V8 全量既有 + golden 四快照字节不变 + 迁移一致性 | 既有套件 |

## 2. tests/v8.5/ 套件（九件）

| 套件 | 关键断言 |
|---|---|
| test_relationship_model.py | 6 维默认/clamp/档位；stage 对新维度不敏感；distance_index 边界 |
| test_interaction_signal.py | 词表矩阵、novelty 衰减、信号→事件映射（neutral 降档）、证据窗重建等价、零新增 LLM 请求 |
| test_evolution_engine.py | D1~D5 逐条（含 0.0063 精确值）、顺序固定、限速扩 6 维、里程碑独立预算、关闭开关=V5 逐位 |
| test_relationship_replay.py | 随机事件流（固定种子）重放终态全等 ×100；回滚=关键帧+重放 |
| test_milestone_system.py | 12 谓词正反例、unique 幂等、bonus cap、解锁查询、补检 |
| test_conflict_system.py | 迁移矩阵全格、时序四条（注入时钟）、neglect 分档、tension 日消退幂等、system 行对账白名单 |
| test_relationship_memory.py | 路由边界表逐格、importance 映射、模板确定性、24h 去重、零侵入 |
| test_relationship_context.py | **默认态 golden 字节相等**、追加行条件与预算截断、B1~B5、relationship_ctx=None=V6.5 逐位 |
| test_relationship_autonomy.py | 不传新字段=V7 逐位、R1~R5 正反例、R5 覆盖 R3、reason 进 decision_records |

集成与 E2E 归位 tests/integration/、tests/e2e/（命名避免跨套件重名——xdist loadscope 下同名文件分组的既有教训）。

## 3. 黄金不变量测试（机器可证底线）

```python
def test_golden_default_relationship_unchanged():
    # 默认态（friend + 新维默认值 + 无里程碑/冲突/neglect）
    # build_relationship_section 输出 == V5 现状字符串（逐字节）
    # 且四个 golden 快照测试原样通过（零重生成）
```

偏离态另测：respect 偏档/里程碑/冲突各注入一态，断言追加行出现且默认态测试仍绿——"条件化追加"的两侧都锁死。

## 4. 评估护栏测试（题设场景直测）

- **relationship_jump**：首回合注入 trust 0.35→1.0 → fail + 实际生效值被限速截断 ≤0.17。
- **relationship_uncaused_change**：直改状态不落账 → fail。
- **relationship_rate_violation**：日累计注入超 0.30 → warn。
- **conflict_state_invalid**：none→resolved 跳迁注入 → fail。
- 报告落 evaluation_reports（verdict/scores/issues），/debug/turns/{id}/evaluation 可查。

## 5. 性能护栏（常驻守门，对齐 V7.8/V8 口径）

演化流水线在 state_update 步骤内的增量预算断言：

```text
纯信号+演化（无 LLM、无 IO 注入）< 10ms/轮
全链（含仓储写入、里程碑/冲突检测）< 25ms/轮（FakeLLM、内存 DB 口径）
回答生成路径零感知：answer_chain 前的耗时分布不含演化（trace 断言）
```

## 6. 并行与隔离纪律（既有教训固化）

- 时间敏感测试（neglect 天数、cold 12h、tension 日消退）一律注入时钟/日期，不吃真时钟（V7.8-012 种子错开教训的根因消除）。
- 测试默认 `rel_evolution_enabled=true` 走新路径 + 显式关闭用例锁退化路径；评估维度开关独立可关（V7.5"测试默认关评估"教训按需沿用）。
- 新增测试文件命名全局唯一；每测试独立 DB（conftest 既有保障）；不引入模块级可变全局（xdist 不可依赖）。

## 7. 回归底线（每个 Task 的完成定义）

```text
1. 全量既有测试（1069+）零失败
2. golden 四快照字节不变（V8.5 不改默认渲染 → 允许零重生成）
3. 迁移一致性测试通过（TEST_DATABASE_URL 环境下）
4. 新增套件全绿
5. V8 若已实现：tests/v8/ 场景套件零回归（互不干扰验证）
```

## 8. 人工回归（上线前）

V8.5-008 产出 `docs/roleplay-v8.5/regression-checklist.md`：开关矩阵（演化/里程碑/冲突三开关 × 开关组合）、五条真实模型演练（首次袒露、承诺兑现与违背、冲突→道歉→和解全链、两周疏远→召回、30 天日常累计）、prompt 关系段抽查、时间线与回滚演练、体积与限速观察项。组织方式沿用 V4/V7/V7.5/V7.8 清单。
