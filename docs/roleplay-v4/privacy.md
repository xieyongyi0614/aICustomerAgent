# Privacy & Safety

## 1. 用户记忆控制指令

| 用户说 | Extractor 输出 | 效果 |
|---|---|---|
| "不要记住这件事""别存这个" | action=suppress | 本轮所有 candidate 丢弃（Policy R2） |
| "忘了吧 / 删掉那条关于……的记忆" | action=forget + content 提示 | 匹配 active 记忆 → **硬删除**；匹配不到 → trace 记 miss，不猜测删除 |
| "我已经不喜欢咖啡了""其实不是这样" | action=invalidate | 旧记忆 status=invalidated（软失效，保留审计） |

- 指令识别由 Extractor LLM 完成，但**执行由代码强制**：Policy 层看到 action 即执行，不再询问。
- suppress 是本轮全量阻断：即使用户同轮说了别的事实（"别记住这件事，对了我在深圳工作"），V4 保守处理——整轮不保存（宁可漏记，不可违背用户意愿）。

## 2. 删除 / 更新 / 失效语义

- **删除（forget）**：物理删除行。仅此一种情况硬删；其余一律软状态（superseded/invalidated），保留"为什么角色忘了这件事"的可解释性。
- **更新（update/supersede）**：见 memory-conflict.md。
- **失效（invalidate）**：status 置 invalidated，召回/注入/Debug 列表均不可见。

## 3. Debug / API 侧

- `GET /debug/memories` 类接口（V1 已有 debug state history 模式）扩展：只返回 active + 变更历史（含 status）。
- 用户不可见任何记忆 UI；记忆只在角色语气中自然体现。

## 4. 安全边界

- 记忆只存本地 PostgreSQL，不外发第三方（LLM 上下文注入除外，属功能必需）。
- 记忆 Prompt 注入时只含 content + type，不暴露内部 id/状态字段，降低 Prompt 注入面。
- 单条 content ≤ 50 字 + 单轮 ≤ 3 条 candidate：即使用户刷屏，库增长有硬上界；超上限候选丢弃。
- 长期总量控制：expires_at 回收 + invalidated 定期归档，单用户 active 记忆软上限 200 条（达到后丢弃最低 importance 的候选，不自动删用户记忆）。

## 5. 验收标准

- Case 7（用户要求删除）：记忆被删除且后续召回不再出现。
- Case 8（用户修改旧记忆）：旧记忆失效、新记忆生效。
- suppress 轮次零写入（含高 importance candidate）。
