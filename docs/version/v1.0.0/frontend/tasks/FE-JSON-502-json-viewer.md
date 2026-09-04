# FE-JSON-502 · 自研 JsonViewer 折叠树

## Task ID

FE-JSON-502

## Task Name

JsonViewer：递归折叠树、mono 呈现与一键 copy

## Type

FE

## Priority

P1

## Description

自研轻量 JSON 查看组件（架构决策：不引第三方大件），供 TraceStepDetail、RawPanel、各卡片的「查看原始 JSON」使用。

## Scope

- 递归渲染任意 JSON 结构：object/array/primitive 三形态；key 折叠/展开（默认展开深度 2 层）
- 全部文本 mono 字体；值类型着色（字符串/数值/布尔/null 区分色，暗色可读）
- 一键 copy：单节点 copy 与整体 copy（lib copy 工具，含降级方案）
- 大对象保护：超过阈值节点数/字符数时默认折叠并提示「过大已折叠」，避免一次渲染数万节点
- 展开全部 / 折叠全部操作

## Out of Scope

- JSON 编辑能力（纯只读）
- 虚拟滚动（超大对象靠默认折叠保护即可，Phase 3 再评估）

## Dependencies

- FE-THEME-002

## Input

- 架构文档第 4 节（Code/JSON Viewer 约定）、第 10 节详情区要求

## Output

- features/json-viewer 组件 + lib/copy 工具

## Business Rules

- 只读安全渲染：对循环引用/异常输入容错显示原始字符串，不崩白屏
- 折叠状态为组件内部态即可（不持久化）

## API Dependencies

- 无

## Data Dependencies

- 无（入参为普通对象）

## Permission

- 同全局：无鉴权

## Error Handling

- 入参 undefined/null 渲染空态占位；非法 JSON 字符串直接按文本展示

## Acceptance Criteria

- 嵌套 ≥4 层对象渲染与折叠正确；copy 内容与源一致（剪贴板断言或降级提示可见）
- 构造 10k+ 键对象：首屏因默认折叠保持流畅

## Test Requirements

- 组件测试：三类节点渲染、折叠交互、copy 回调内容断言、超大对象默认折叠
