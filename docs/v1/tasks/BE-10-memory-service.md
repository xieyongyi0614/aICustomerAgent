# BE-10 memory_service（长期记忆）

| 字段 | 内容 |
|---|---|
| Task ID | BE-10 |
| Task Name | memory_service（提取落库 + 检索） |
| Type | BE |
| Priority | P0 |

## Description

实现 `app/services/memory_service.py`：每轮对话后调用 extractor_chain 提取值得保存的信息并落库（含重要度阈值过滤与去重）；用户输入时检索相关记忆返回。实现 V1 功能目标三/四/五。

## Scope

- `extract_and_save(user_id, user_input, ai_reply)`：
  - 调用 BE-09 `extract()`
  - `should_save and importance >= settings.MEMORY_IMPORTANCE_THRESHOLD(0.6)` 才入库
  - `exists_similar` 去重（DB-04）
- `retrieve(user_id, user_input, top_k) -> list[UserMemory]`：
  - V1 关键词匹配：用户输入与记忆内容词重叠度打分，返回 top-k 且分数 ≥ 阈值
  - 接口签名对齐未来向量检索（P2 只换实现）

## Out of Scope

- 提取判断本身（BE-09）
- 检索算法升级为 embedding（P2）
- 记忆管理 API（P2）

## Dependencies

- BE-03（UserMemory / MemoryDecision）
- BE-09（extractor_chain）
- DB-04（memory_repository）

## Input

- `app/chains/extractor_chain.py`
- `app/repositories/memory_repository.py`
- `settings.MEMORY_IMPORTANCE_THRESHOLD`、`MEMORY_TOP_K`

## Output

- `app/services/memory_service.py`

## Business Rules

1. 保存条件：`should_save == True` 且 `importance >= 0.6`，两个条件缺一不保存。
2. 去重：`exists_similar` 命中则不重复插入（V1 全等/包含判断）。
3. 检索：打分 = 用户输入词与记忆词的重叠数 / 记忆词数（或等价稳定算法）；低于阈值不返回；结果按分数降序取 top_k。
4. `retrieve` 的对外签名固定：`(user_id, user_input, top_k=None) -> list[UserMemory]`，实现可整体替换。

## API Dependencies

- 无

## Data Dependencies

- `memories` 表（经 DB-04）

## Permission

- 无鉴权要求。

## Error Handling

- extract 解析失败：跳过本轮提取，记录日志，不影响对话。
- 检索无匹配：返回空列表。
- DB 异常：落库失败回滚，不影响本轮回答（记忆是增益而非必须）。

## Subtask 拆分

- S1：`extract_and_save`（阈值 + 去重 + 落库）
- S2：`retrieve` 关键词打分
- S3：接口签名定稿（为向量检索留缝）

## Acceptance Criteria

- "我喜欢日本料理，尤其是寿司" → 落库为 preference，importance≥0.6
- "今天吃了拉面" → 不落库
- 相同内容重复出现 → 不产生第二条记录
- 输入"想吃点什么" → `retrieve` 返回寿司偏好
- importance=0.5 的保存请求被过滤（低于 0.6）

## Test Requirements

- 保存/过滤/去重/检索四条路径全覆盖。
- 检索空结果返回空列表。