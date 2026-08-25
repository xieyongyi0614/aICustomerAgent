# FE-LAYOUT-003 · Workbench 双栏布局与响应式阶梯

## Task ID

FE-LAYOUT-003

## Task Name

Workbench 双栏布局壳、Debug 折叠与响应式阶梯

## Type

FE

## Priority

P0

## Description

实现应用主布局壳：顶部 TopBar 区域位 + 左 ChatPane（约 42%）+ 右 DebugPane（约 58%，可整体折叠），以及架构文档定义的三档响应式降级。为后续所有面板提供挂载容器。

## Scope

- Workbench 布局组件：双栏 flex 结构、ChatPane/DebugPane 容器、TopBar 高度区占位
- DebugPane 整体折叠/展开切换（折叠时 Chat 全宽）；折叠状态存 localStorage
- 响应式阶梯：≥1200px 正常双栏；<1200px DebugPane 收窄至固定约 480px；<1024px DebugPane 转 Drawer（由 TopBar 唤起按钮触发，本任务先提供 Drawer 容器与唤起状态，按钮接线在 FE-TOPBAR-004）；<768px 顶部提示条「请使用桌面端」
- ScrollArea 在两栏内的滚动容器基座
- 各面板 Tab 位占位（空态文案「Phase 2 提供」）

## Out of Scope

- TopBar 内容本身（FE-TOPBAR-004）
- Chat/Debug 的内部业务组件
- 移动端专属布局（明确不做）

## Dependencies

- ARCH-FE-001、FE-THEME-002

## Input

- `docs/frontend/frontend-architecture.md` 第 4 节（ASCII Layout 与响应式阶梯）

## Output

- Workbench 布局组件树 + 折叠状态管理（局部即可）
- 各宽度断点下的可用布局

## Business Rules

- Debug 折叠不得卸载已挂载面板的数据状态（视觉隐藏而非销毁，具体策略由实现选择但需保证切回不重拉）
- 布局不因内容长短抖动：两栏各自独立滚动

## API Dependencies

- 无

## Data Dependencies

- 无

## Permission

- 同全局：无鉴权

## Error Handling

- localStorage 不可用（隐私模式）时折叠状态退化为内存态，不报错

## Acceptance Criteria

- 四个断点行为符合阶梯定义（手工缩放窗口验证并记录）
- 折叠/展开流畅，刷新后记住折叠偏好
- 占位 Tab 与空态文案可见

## Test Requirements

- 布局组件渲染测试（给定视口尺寸断言结构类名/行为）
- 折叠切换交互测试
