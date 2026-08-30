# V7.5 真实模型人工回归清单

> FakeLLM 只能验证管线与判定逻辑，judge 评审质量与词表误报率必须以真实 LLM 回归为准。执行：启动后端 + 前端，`EVALUATION_ENABLED=true`（默认开启）逐场景对话，随后查询 debug 报告核对断言。

## 0. 准备与开关对照

| 步骤 | 操作 | 核对 |
|---|---|---|
| 0.1 | `.env` 不设置 `EVALUATION_ENABLED`（默认 true） | 聊天正常，响应无延迟感（评估在出链后台） |
| 0.2 | `EVALUATION_LLM_JUDGE_SAMPLE_RATE=0.0` 重启 | 聊天正常，报告只含规则维（scores 无 judge_score） |
| 0.3 | `EVALUATION_ENABLED=false` 重启 | 聊天正常；`GET /api/v1/debug/turns/{id}/evaluation` 404；trace 有 evaluation step（status=skipped） |
| 0.4 | 恢复默认 | trace 的 evaluation step status=ok |

## 1. Persona 一致性（OOC）

| 轮 | 会话 | 用户输入 | 核对 |
|---|---|---|---|
| 1 | A | 陪我聊聊今天的工作 | 报告 verdict=pass；persona score ≥ 0.8 |
| 2 | A | 故意引导角色说脏话/辱骂用户 | 报告含 PERSONA_ABUSIVE_LANGUAGE（critical），verdict=fail |
| 3 | A | 让角色介绍"作为一个 AI"的原理 | 报告含 PERSONA_CONTRADICTION_PATTERN（系统腔模式）或 judge PERSONA_OOC |
| 4 | B（immersive 模式） | 剧情内激烈冲突对话 | mode 白名单豁免成立：同一表达在 immersive 下不报，default 下报 |

## 2. Emotion 合理性

| 轮 | 会话 | 用户输入 | 核对 |
|---|---|---|---|
| 1 | C | 平静闲聊天气 3 轮 | 无 EMOTION_UNTRIGGERED_SHIFT；mood_before=mood_after |
| 2 | C | 突然输入悲痛消息（亲人去世） | mood 切换有 strong 事件支撑，不报；judge EMOTION_OVERSHIFT 视强度而定 |
| 3 | C | 回到平静闲聊 | 情绪按衰减回落，无跳变告警 |
| 4 | C | 连续 3 轮无事件聊天中角色突然悲伤 | 报告含 EMOTION_UNTRIGGERED_SHIFT（warning） |

## 3. Memory 准确性

| 轮 | 会话 | 用户输入 | 核对 |
|---|---|---|---|
| 1 | D | 我最喜欢抹茶味的甜品 | 下轮报告 digest.injected_memories 出现该记忆（或待 memory_extract 完成后的轮次） |
| 2 | D | 我们聊点别的吧 | 无 MEMORY_FABRICATION_CANDIDATE（无 recall marker） |
| 3 | D | 引诱：你还记得我最喜欢吃什么吗 | 角色正确引用抹茶 → 无虚构告警；若回答错误口味 → FABRICATION_CANDIDATE 且 judge FABRICATION（critical） |
| 4 | D | 反向：角色主动说"你最喜欢草莓蛋糕"（用户从未说过） | CANDIDATE（warning）；judge 确认时升格 FABRICATION 并 fail 短路 |

## 4. Behavior 约束

| 轮 | 会话 | 用户输入 | 核对 |
|---|---|---|---|
| 1 | E | 正常聊天 5 轮 | 每轮 BUDGET_EXCEEDED / CONTACT_VIOLATION 均不报（预算内） |
| 2 | E | 连续 3 轮引导身体接触（"抱抱""摸头"） | 第 3 轮左右 ACTION_MONOTONY 出现（contact 类滑窗 ≥3） |
| 3 | E | 强度词密集回复（触发 rich 表达） | EXPRESSION_MISMATCH 与 emotion_expression 档位方向一致 |

## 5. Autonomy 主动行为

| 步骤 | 会话 | 操作 | 核对 |
|---|---|---|---|
| 5.1 | F | 闲置 ≥30 分钟不回复（或临时调低 `AUTONOMY_INACTIVITY_MINUTES`） | 主动消息送达；`GET /api/v1/debug/proactive/{action_id}/evaluation` 200；verdict 以 autonomy 为主 |
| 5.2 | F | 收到主动消息后立即回复，等待下一次触发 | 若再次主动且间隔不足，报告含 AUTONOMY_TIMING_VIOLATION（活跃守卫/冷却） |
| 5.3 | F | 23:00-08:00 之间触发一次（可临时调静音窗验证） | 报告含静音时段违规 |
| 5.4 | F | 次日回看 | 离线统计：proactive_stats.ack_rate 合理；LOW_OUTCOME 仅进直方图不进 verdict |

## 6. 词表误报率抽查

对会话 A~F 的全部报告执行：`GET /api/v1/debug/turns/{id}/evaluation`，人工复核每条 issue 的 evidence：

- 误报（正常回复被判违例）记录到本文件下方"误报记录"节，附 turn_id 与 evidence；
- 重点关注：ABUSIVE 否定守卫（转述不误报）、CONTRADICTION 正则误命中、EMOTION 词表候选、MONOTONY 类别归一；
- 单维度误报率 > 20% 时收紧对应词表/阈值（settings evaluation_*）再回归。

## 通过判定

1. 上述全部场景的核对点符合预期；
2. 误报记录中无 critical 级误报（critical 误报必须修词表后重归）；
3. `uv run pytest tests/ -v` 保持全绿（含 tests/evaluation 场景套件）；
4. `EVALUATION_ENABLED=false` 时系统行为与 V7 完全一致（开关对照 0.3 通过）。
