# FE-POLISH-602 · 全局打磨与性能评估

## Task ID

FE-POLISH-602

## Task Name

统一空态/错误态、可用性细节打磨与长会话性能评估

## Type

FE

## Priority

P2

## Description

Phase 3 收口任务：统一全部面板的加载/空/错三态呈现，补齐易用性细节，并对长会话做一次性能实测以决定是否引入虚拟滚动。

## Scope

- 三态统一：加载骨架、空态引导、错误卡片（含重试）在 Overview/State/Memory/Trace/Raw 五 Tab 与 Chat 区的一致化收口
- 细节打磨：数值格式统一（时长/百分比/相对时间的单一出处）、tooltip 文案校对、键盘可达性基础检查
- 性能实测：构造 500+ 条消息会话与 20+ 轮 trace 记录，度量流式渲染帧率与面板切换耗时；仅当不达标时引入虚拟滚动（记录决策）
- 清理 Phase 1 的临时演示入口与临时调试代码

## Out of Scope

- 新功能
- 动画/视觉演出（明确不做）

## Dependencies

- 全部 P0/P1 面板任务完成

## Input

- 架构文档第 2 节铁律、第 13 节 Phase 3 规划

## Output

- 打磨后的整体 UI + 性能实测结论（达标数据或虚拟滚动改造）

## Business Rules

- 任何打磨不得改变既有交互契约（联动、轮询、Mock 切换语义不变）
- 虚拟滚动若引入，必须保持 AutoScroll 行为等价

## API Dependencies

- 无新增

## Data Dependencies

- 无新增

## Permission

- 同全局：无鉴权

## Error Handling

- 收口阶段发现的错误态缺失逐项补齐并登记清单

## Acceptance Criteria

- 五个 Tab 空态/加载态/错误态呈现风格一致
- 性能实测报告：500 消息 + 流式中输入无卡顿，或虚拟滚动已落地并验证
- 临时演示代码零残留（grep 验证）

## Test Requirements

- 回归：全部既有组件测试保持通过
- 性能测试记录留档（数字写入任务完成说明）
