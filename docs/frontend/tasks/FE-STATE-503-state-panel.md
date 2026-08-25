# FE-STATE-503 · StatePanel（角色状态卡 / 关系卡 / 情绪历史条）

## Task ID

FE-STATE-503

## Task Name

StatePanel：CharacterStateCard、RelationshipCard 与 EmotionHistoryStrip

## Type

FE

## Priority

P1

## Description

实现 State Tab 的三块可视化：角色当前状态、关系三维与阶段、最近情绪/事件历史。核心价值是「数值可视化 + stage 阈值刻度」，让 V2 的数值规则肉眼可见。

## Scope

- CharacterStateCard：mood Badge、energy Progress（0–1）、current_topic、inner_state 全文、updated_at 相对时间
- RelationshipCard：intimacy/trust/familiarity 三条 Progress，叠加阈值竖标刻度线（friend 0.35 familiarity 线、close_friend 0.55 双线、partner 0.75 双线，阈值常量集中管理）；stage Badge；「距下一阶段」提示行（按后端阈值规则计算还差多少，标注为前端推断）
- EmotionHistoryStrip：最近 N 轮 emotion/event 点列（Badge 小圆点 + hover 详情），横向时间线形态
- 数据经 useCharacterState（API-FE-501）获取；加载骨架、局部错误卡片、手动刷新接线

## Out of Scope

- 状态写入口（永远不做）
- emotion_history 分页浏览（仅最近 N 条）

## Dependencies

- API-FE-501、FE-JSON-502（每卡附「查看原始 JSON」入口）、FE-THEME-002、FE-LAYOUT-003（Tab 挂载位）

## Input

- 架构文档第 4 节 Progress 刻度约定、第 6 节 CharacterState/RelationshipState 模型
- V2 架构文档 4.4 节 stage 阈值（0.35/0.55/0.75 与迟滞带说明）

## Output

- StatePanel 及三个子组件 + 阈值常量

## Business Rules

- 数值一律 mono 呈现；阈值刻度线颜色区别于进度条本体色
- 「距下一阶段」是展示层推算：迟滞带导致的降级条件不在本提示内表达（避免误导），tooltip 注明规则出处
- 卡片间相互独立：任一数据缺失只影响本卡

## API Dependencies

- GET /api/v1/state（经 useCharacterState）

## Data Dependencies

- character_state / relationship_state / emotion_history 快照字段

## Permission

- 同全局：无鉴权

## Error Handling

- 接口失败 → 本 Tab 错误卡片 + 重试按钮；其他 Tab 不受影响

## Acceptance Criteria

- 给定快照：三条 Progress 数值与刻度位置正确；stage Badge 用对应色板
- updated_at 陈旧（>12h 闲置恢复窗口）时有视觉提示（如时间戳变灰加 tooltip）
- mock fixture 三套 persona（空状态/富状态/临升级）渲染均正确

## Test Requirements

- 组件测试：给定快照断言渲染值、刻度位置比例、距下一阶段文案
- 错误态/加载态各一用例
