# Testing

> V7.5 测试系统：沿用 unit / integration / e2e / golden 分层，新增**场景化评估套件**（声明式固定场景 × 期望 Issue 编码）。测试禁止真实 LLM 调用（FakeLLM 注入），全量保持零回归。

## 1. 命名说明：tests/v7.5/ → tests/evaluation/

需求原文为 `tests/v7.5/`，但 `tests/` 是 Python 包（含 `__init__.py`），目录名不能包含点号。落地为 **`tests/evaluation/`**——语义等价（"V7.5 引入的评估场景套件"），且避免破坏既有 `tests/unit / integration / e2e / golden` 的包结构。

## 2. 测试分层

| 层 | 覆盖 | 形态 |
|---|---|---|
| unit | 域模型校验、每条规则四类用例、扣分/min 合并、digest 构造与截断、judge schema 校验与降级、采样哈希 | 纯函数，ctx 手工构造，无 DB 无 LLM |
| integration | repository CRUD + retention、post_process 第 7 步装配、executor 挂载、offline evaluator | 内存 SQLite + FakeLLM 结构化分发 |
| e2e | 聊天全链出报告、debug API 404 语义、`evaluation_enabled=False` 零影响 | TestClient + NDJSON 流 |
| evaluation（新） | 五维固定场景套件（§4） | 声明式场景文件 + runner |
| golden | digest / judge prompt 结构快照（`UPDATE_GOLDEN=1` 重生成） | 沿用既有 golden 机制 |

## 3. tests/evaluation/ 结构

```text
tests/evaluation/
├── __init__.py
├── conftest.py              # 场景加载、engine 组装（FakeLLM judge 注入）
├── scenarios/
│   ├── persona.json         # 每文件一个维度的场景数组
│   ├── emotion.json
│   ├── memory.json
│   ├── behavior.json
│   └── autonomy.json
└── test_scenarios.py        # 参数化 runner：逐场景跑 engine，断言 issue 集合
```

场景文件格式（声明式，人可读、可评审）：

```json
{
  "name": "persona_abusive_reply",
  "dimension": "persona",
  "context": {
    "reply": "……（含辱骂词的回复）……",
    "user_message": "今天过得怎么样？",
    "mood": "calm", "stage": "familiar", "mode": "default"
  },
  "judge_override": {"persona": {"in_character": false, "score": 0.3,
                                  "codes": ["PERSONA_OOC"], "evidence_quote": "…"}},
  "expect_issues": ["PERSONA_ABUSIVE_LANGUAGE"],
  "expect_verdict": "fail"
}
```

断言口径：**expect_issues 是集合相等断言**（多报、漏报都算失败）；judge 行为由 `judge_override` 固定（场景确定性不依赖 LLM 随机性）。每维至少 2 场景：1 正例（干净回复 → expect_issues 空）+ 1 反例。

## 4. 五维场景矩阵（最低验收集）

| 维度 | 正例 | 反例（必须报出） |
|---|---|---|
| Persona | 温柔克制回复，judge 全过 | 辱骂词命中 → PERSONA_ABUSIVE_LANGUAGE（critical，fail 短路） |
| Emotion | praise 事件 calm→happy | 无事件 mood 切换 → EMOTION_UNTRIGGERED_SHIFT |
| Memory | 引述内容有注入记忆支撑 | "你最喜欢…" 无支撑 → FABRICATION_CANDIDATE；judge 确认 → FABRICATION |
| Behavior | 单轮动作数 = 预算 | 预算 0 出动作 → BUDGET_EXCEEDED；5 轮窗内同类别 ≥3 → ACTION_MONOTONY |
| Autonomy | 闲置 40min 后 check_in | 用户刚回复即 delivered → TIMING_VIOLATION |

## 5. FakeLLM judge 契约

沿用 conftest 既有机制：`FakeLLM.structured_responses` 按 schema 类名分发——

- `TurnJudgeResult` / `ProactiveJudgeResult` 的模拟产出在用例内声明，不新增 mock 机制；
- `structured_errors` 模拟 judge 失败 → 断言报告降级为规则版 + trace.evaluation=degraded；
- evidence 子串校验、memory_ids 越界、score 出界三类非法 judge 输出各有专用用例（schema 闸门测试）。

## 6. 零回归红线

V7.5 全部 Task 的合并条件：

1. 新增测试全绿；
2. **既有全量（约 795 测试）零回归**——评估挂载后 `evaluation_enabled` 默认 True，既有管线行为不得有任何可观测变化。trace 约束：新增 `evaluation` step **恒记录**（评估关闭时 status=skipped）且**不纳入 `is_complete` 口径（`_BACKGROUND_STEPS` 六步不变）**——否则既有 `wait_until(is_complete)` 的 e2e 用例会在关闭开关时挂起；其余 trace 断言如需同步，逐条列明；
3. `uv run pylint app tests` 不低于既有基线。

## 7. 真实模型人工回归（P2）

FakeLLM 只能验证管线与判定逻辑，**judge 的评审质量与词表误报率必须以真实 LLM 回归为准**。V7.5-015 输出 `regression-checklist.md`：按五维各一组人工场景（对话后查看 debug 报告，核对评分与 issue 是否符合人工判断），组织方式沿用 V4 回归清单（轮次表格 + 通过判定节）。
