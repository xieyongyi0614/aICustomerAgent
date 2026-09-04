# FE-THEME-002 · 设计 Token、暗色主题与 shadcn 基础组件

## Task ID

FE-THEME-002

## Task Name

设计 Token、暗色唯一默认主题与 shadcn 基础组件引入

## Type

FE

## Priority

P0

## Description

落实架构文档第 4 节的设计 Token 约定：暗色为唯一默认主题、sans/mono 双字体栈、Badge 枚举固定色板、Progress 阈值刻度样式基座，并引入后续所有任务依赖的 shadcn 基础组件。

## Scope

- 暗色主题全局变量（背景 / 卡片面 / 边框 / 三级文本色 / 状态色 ok-warn-error）
- 字体栈：UI 用系统 sans 栈；数值场景用 mono 栈（提供工具类或语义 class 约定）
- Badge 枚举色板常量表：mode 三档、8 种 emotion、7 种 behavior、4 种 stage、degraded 状态——同一枚举全局一色，集中一处定义映射
- Progress 细条样式基座（0–1 数值），预留阈值刻度线插槽（刻度数据由使用方传入，本任务只做样式承载）
- 引入 shadcn 组件：button、badge、card、tabs、dialog、drawer、scroll-area、progress、tooltip、input、textarea
- 一个临时演示入口（dev 才可见的路由或挂载点）展示全部 token 与组件形态，供人工验收

## Out of Scope

- 具体面板/卡片业务组件（StatePanel 等在 FE-STATE-503 等）
- JsonViewer（FE-JSON-502）
- 亮色主题、主题切换器（明确不做）

## Dependencies

- ARCH-FE-001

## Input

- `docs/version/v1.0.0/frontend/frontend-architecture.md` 第 4 节（UI Layout 中设计 Token 表）
- 后端枚举定义：`docs/version/v1.0.0/v2/v2-architecture.md` 第 3 节（mood/emotion/event/behavior/stage 取值）

## Output

- Token 常量与色板映射集中文件（types/domain 或 lib 下）
- shadcn 组件进入 `src/components/ui/`
- 演示入口页面

## Business Rules

- 一切数值类展示必须可套用 mono 字体约定
- 枚举色板以「枚举值 → 语义色」映射表形式集中管理，禁止在组件内散落写死颜色
- 信息密度优先：间距遵循 4px 基数，卡片 1px 边框 + 8px 圆角、无阴影或极浅阴影

## API Dependencies

- 无

## Data Dependencies

- 无（色板覆盖的枚举值清单来自后端模型文档，属静态知识）

## Permission

- 同全局：无鉴权

## Error Handling

- 未知枚举值（后端未来新增）时 Badge 回退中性灰样式，不抛错

## Acceptance Criteria

- 演示入口可见：全部枚举 Badge 色板、Progress（含刻度线示例）、各 shadcn 组件暗色形态
- 色板映射表覆盖架构文档列出的全部枚举值
- 亮色不存在：全局无亮色主题入口，html 根为暗色

## Test Requirements

- 色板映射表单测：每个已知枚举值有映射、未知值回退中性色
- 组件冒烟：演示页渲染无控制台错误
