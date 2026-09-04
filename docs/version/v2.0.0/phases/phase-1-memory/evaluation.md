# Phase 1 Evaluation — Memory 2.0

> 指标体系沿 [../../architecture/evaluation.md](../../architecture/evaluation.md)；本文件为 P1 的门槛化落地。Gate 未全过不得申请开启 `v2_memory_enabled`（migration §6 验收门）。

## 指标与门槛（Eval Gate）

| ID | 指标 | 测法 | 门槛 |
|---|---|---|---|
| E-MEM-01 | Memory Precision | 标注集：注入事实→间隔对话→查询，核对召回归因 | ≥0.9 |
| E-MEM-02 | 冲突处理正确率 | 用户改口→旧记忆 superseded 而非并存 | 100%（保守并存 pending 场景除外，需 trace） |
| E-MEM-03 | 显式命令正确率 | 「记住 X」0 LLM 转正；「忘掉 X」三通道 0 命中 | 100%；误删率=0 |
| E-MEM-04 | 语义召回 Recall（改述） | 同义不同词查询离线集 | ≥0.8 |
| E-MEM-05 | Roleplay/假设拦截率 | 假装/如果场景 → hypothetical 标记 | 100% |
| E-MEM-06 | Context 注入合规 | 检索段 ≤800 合并预算、无 hypothetical 注入 | 100%；总预算 ≤12000 |

## 场景集（离线，offline_evaluator）

跨 Phase 通用 10 类场景见 architecture/evaluation.md §2；P1 重点子集：短期对话 / 长期对话（50+ 轮）/ 跨 Conversation / 用户纠正 / 显式记住 / 显式忘记 / Roleplay / 假设性 / 错误信息 / 冲突信息。规模：先 100 条（每类 ≥10），随 Phase 累积。

## 执行方式

- Flag ON 影子环境跑全场景集；Flag OFF 跑 golden 对比。
- Judge 采样复用 evaluation_judge（离线批量）。
- 每次灰度推进前全量重跑，报告归档至本目录。

## Regression Gate

见 [regression-checklist.md](regression-checklist.md)。
