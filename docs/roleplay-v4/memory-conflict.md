# Memory Conflict

## 1. 背景

"用户喜欢咖啡"半年后变成"我现在不喝咖啡了"。V1 的 exists_similar 字符串去重会直接丢弃新信息，或（去掉去重后）产生两条矛盾记忆。

## 2. 三种冲突动作

| 动作 | 触发条件 | 效果 |
|---|---|---|
| **update** | 新 candidate 与旧记忆同类型且语义高度相似（子串包含或关键词重合 ≥ 阈值），新信息是旧信息的精化/补充 | 直接更新旧行 content/importance，保留 created_at，刷新 updated_at |
| **supersede** | 新旧同主题但内容实质不同（如"喜欢咖啡"→"喜欢喝茶"），新信息更新 | 旧行 status=superseded + superseded_by=新行 id；新行 active |
| **invalidate** | 新信息明确否定旧信息（"我不…了""其实不是"），Extractor 输出 action=invalidate + target 提示 | 旧行 status=invalidated，不建新行（否定 ≠ 新事实） |

## 3. 匹配实现（第一版，纯代码）

- 匹配范围：同 user + 同 character_id + 同 type + status=active。
- 相似判定：沿用并强化 exists_similar——分词 jaccard ≥ 0.6 视为同主题（阈值 settings.memory_conflict_threshold）。
- update vs supersede 区分：Extractor 在 candidate 中输出 `relation: refine | replace | negate`（LLM 判定语义关系），代码只执行；判定缺失时默认 supersede（保守，宁可保留历史不覆盖）。
- **不追求完美**：误 supersede 的代价是丢一条旧记忆（仍有 status 审计痕迹），误存矛盾记忆的代价是角色说话自相矛盾——后者更糟，所以策略偏向 supersede/invalidate。

## 4. 无法自动处理的冲突

- 同轮内两条 candidate 互相矛盾：全部丢弃该对（信息不可靠），trace 记 warning。
- 跨类型冲突（preference vs fact 冲突）：不处理，两者可并存（"养猫"与"不喝咖啡"不冲突）。

## 5. 边界情况

- superseded 链（A→B→C）：只允许单跳引用，召回永远只取 active。
- 旧记忆被 invalidate 后用户又重新表达同样内容：正常 save 新 active 行（历史 invalidated 行不复活）。

## 6. 验收标准

- Case 6（咖啡冲突）：更新后只剩一条 active 记忆，无矛盾。
- Case 8（用户修改旧记忆）：旧记忆 superseded，新记忆 active。
- superseded/invalidated 记忆不被召回、不出现在 Prompt。
