# Testing

## 1. 约定

沿用：pytest + pytest-asyncio、FakeLLM 注入、单元测试内存 SQLite、HTTP/e2e 连 PostgreSQL、测试禁止真实 LLM。

## 2. 测试矩阵（17 项必测）

### Emotion（1~5）

| # | Case | 断言 |
|---|---|---|
| 1 | 用户夸奖角色 | happy intensity 按档位上升，cause 正确 |
| 2 | 用户安慰角色 | comforted → happy；tension 若 >0 有小幅消耗 |
| 3 | 用户批评角色 | criticized → sad；strong 档受 0.4 单轮上限约束 |
| 4 | 情绪衰减 | 时间注入：0.55 强度 1.5h 后 ≈0.25；到底线复位 calm |
| 5 | 新事件覆盖旧情绪 | 强情绪保护（intensity≥0.6 且 confidence<0.8 拒绝切换）；切换带 20% 惯性 |

### Relationship（6~11）

| # | Case | 断言 |
|---|---|---|
| 6 | trust 增长 | user_care/user_help 后 trust 按表上升，event 行落库 |
| 7 | closeness(intimacy) 增长 | intimate_moment → intimacy +0.06（normal） |
| 8 | tension 增长 | conflict → tension +0.20（normal） |
| 9 | 单次变化上限 | strong conflict 单轮每维 ≤0.15、日累计 ≤0.30 |
| 10 | 长期变化 | 30 天 user_care 模拟：trust 缓升、event 表 impact 对账一致 |
| 11 | relationship stage | 阈值升级 / 迟滞防震荡 / tension>0.5 冻结升级 |

### Integration（12~17）

| # | Case | 断言 |
|---|---|---|
| 12 | V3 Scene State | scene_state 读写不受 V5 影响，两管线并行 trace 独立 |
| 13 | V4 Memory | relationship_event 记忆提取照旧；replay 折价 + 一次性限制 |
| 14 | V5 Emotion 全链 | 后台执行、失败不影响回答 |
| 15 | V5 Relationship 全链 | 同上 |
| 16 | Prompt Integration | 段顺序、预算、人格优先约束、无 analysis 兼容 |
| 17 | 多轮回归 | 全量 `uv run pytest tests/ -v`：V2 改造后测试 + V3 + V4 零回归 |

## 3. 附加单测

- `test_emotion_models.py` / `test_emotion_update.py` / `test_emotion_decay.py`
- `test_relationship_models.py` / `test_relationship_events.py` / `test_relationship_update.py`（含三层上限）/ `test_relationship_stage.py`
- `test_prompt_v5.py`（情绪/关系段渲染、预算、兼容）
- `test_memory_replay.py`
- e2e：`test_v5_e2e.py`（多轮：夸奖→情绪升→衰减→stage 缓变全链）

## 4. 真实模型回归（上线前人工）

- "温柔但生气"表现：批评角色后仍保持亚丝娜人格。
- 情绪随多轮自然回落，无跳变。
- tension 升高后角色语气出现距离感，缓和后恢复。
- SSE 首 token 时延无退化。

## 5. 验收标准

17 项全绿 + 附加单测全绿 + V2/V3/V4 零回归；FakeLLM 无法覆盖的表现类问题以真实回归记录为准。
