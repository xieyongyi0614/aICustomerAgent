# Memory Extraction

## 1. 背景

V1 extractor 单段 Prompt + 单条 MemoryDecision，一次只能输出一条记忆，无 source/confidence，无隐私指令识别。

## 2. 目标

每轮对话后台提取 0~N 条 MemoryCandidate，并识别用户的记忆控制指令。

## 3. 设计

- 复用 `chains/extractor_chain.py` + `build_structured_chain`，输出结构改为 `MemoryExtraction(candidates: list[MemoryCandidate])`（0~3 条，上限防刷）。
- Prompt 重写（`prompts/extractor.py`）：
  1. V4 四类定义 + 各类正例反例。
  2. **source 判定规则**：必须标注信息来自用户原话 / 用户可推导 / 模型猜测；`ai_inferred` 会被策略丢弃，Prompt 中明确"不要提交你的推测"。
  3. **去语境化**：content 必须是脱离本轮语境仍成立的陈述句，≤ 50 字。
  4. **隐私指令识别**（privacy.md）：用户说"不要记住这件事 / 忘了吧 / 别存这个" → 输出 `forget`（指向旧记忆，需给出 content 提示供匹配）或 `suppress`（本轮禁止保存）。
- 输入保持 `user_input + ai_reply`，追加最近 2 轮上下文片段以稳定指代消解（"它""那个"），不做摘要。

## 4. 流程

```text
后台任务（_post_process 内，与 state/summary 并行）
user_input + ai_reply + 最近 2 轮
  → extractor（LLM）
  → list[MemoryCandidate]（0~3 条）
  → 逐条进 Memory Policy
```

## 5. 边界情况

- 一轮多条记忆：允许，上限 3 条（settings.memory_max_candidates），防 Prompt 注入刷库。
- 用户明确否定 AI 说的内容：不提取（用户没 stating 新事实）。
- 提取 LLM 失败：丢弃本轮，trace 记 error，不重试（避免重复入库）。

## 6. 验收标准

- Case：偏好/事实/事件各能提取出正确 type 与 content。
- Case：AI 回复中的推测（"你应该很期待吧"）不会产出 candidate（或产出 ai_inferred 被策略丢弃）。
- Case：用户说"忘了吧" → 输出 forget/invalidate 指令。
- 上限 3 条被强制执行。
