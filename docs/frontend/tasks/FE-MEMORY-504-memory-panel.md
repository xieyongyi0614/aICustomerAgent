# FE-MEMORY-504 · MemoryPanel（命中/全量切换 + Extractor 决策卡）

## Task ID

FE-MEMORY-504

## Task Name

MemoryPanel：记忆列表双视图与本轮提取决策展示

## Type

FE

## Priority

P1

## Description

实现 Memory Tab：全量记忆列表与「本轮检索命中」视图切换、单条记忆明细、本轮 Extractor 决策卡（should_save/type/importance/去重结果），回答「为什么提起了这条记忆」「为什么这条没被记住」。

## Scope

- MemoryList：useMemories 拉取全量；hitThisTurn 标记样式（本轮命中高亮描边 + score 显示，若后端返回；V1 未留痕时一律 false 兜底）
- 视图切换：「全部记忆」⇄「本轮命中」（本期命中=无独立数据源时，切换控件置灰并注明依赖后续检索留痕，避免假功能）
- MemoryItem：memory_type Badge、importance 进度条（≥0.6 入库阈值画刻度线，与后端 settings 对齐）、相对时间、展开显示完整 memory 文本
- ExtractorDecisionCard：本轮 should_save、memory_type、importance、去重命中与否（数据来自 turn trace 快照的 extractor 步 output 摘要；缺失时显示「未记录」）
- 加载骨架 / 错误卡片 / 手动刷新接线

## Out of Scope

- 记忆增删改（不做）
- 向量检索分数展示（后端尚无向量）

## Dependencies

- API-FE-501、FE-JSON-502、FE-THEME-002、FE-LAYOUT-003

## Input

- 架构文档第 3 节 Memory Tab 定义、第 6 节 MemoryItem 模型
- V1 架构文档 Task 4 语义（should_save/importance≥0.6 入库、去重）

## Output

- MemoryPanel 及子组件

## Business Rules

- importance 刻度线固定 0.6（与后端入库阈值同源，常量注明出处）
- 列表默认按 created_at 倒序；空记忆显示引导文案（先聊出一条偏好类信息）
- hitThisTurn=false 时绝不伪装命中样式

## API Dependencies

- GET /api/v1/memories（经 useMemories）；Extractor 决策来自 turn trace 快照

## Data Dependencies

- memories 表字段映射；trace 快照 extractor 步摘要

## Permission

- 同全局：无鉴权

## Error Handling

- memories 拉取失败不影响 ExtractorDecisionCard，反之亦然（两块独立错误边界）

## Acceptance Criteria

- fixtures 富记忆 persona：列表、Badge 色、importance 条与刻度、展开明细正确
- 空记忆 persona：空态文案
- should_save=false 的轮次决策卡明确显示「未保存」

## Test Requirements

- 组件测试：列表渲染/展开/空态；决策卡 should_save 两分支
