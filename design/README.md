# design — 朝夕 App 设计稿

## 维护状态（2026-09-27 起）

| 文件 | 状态 |
|---|---|
| `pages/`（11 页 + `index.html` 总览） | **现役维护** —— 设计稿主出口；新增 / 修改页面只改 `pages/` 对应文件 |
| `ai-life-agent-design.html` | 产品设计方案文档，继续维护（§06 视觉规范是色值真源） |
| `ai-life-agent-prototype.html` | **已冻结，不再维护** —— 仅作历史对照存档，不随页面演进同步更新；内容为 pages/ 拆分时的同源快照，与现役页面冲突时以 `pages/` 为准 |

## pages/ 页面清单

| 文件 | 页面 | 冻结原型锚点（仅历史对照） |
|---|---|---|
| `00-login.html` | 登录欢迎页 | `#login` |
| `01-verify.html` | 手机验证码页 | `#verify` |
| `10-home.html` | 首页 · AI Life Center | `#home` |
| `11-briefing.html` | 早间简报（主动式） | `#briefing` |
| `20-chat.html` | 对话 · 旅行规划 Tool Call | `#chat` |
| `21-chat-ledger.html` | 对话 · AI 记账子流程 | `#chatLedger` |
| `30-life.html` | 生活 · Skill 容器 | `#life` |
| `31-ledger.html` | 记账 | `#ledger` |
| `32-health.html` | 健康 | `#health` |
| `40-memory.html` | 记忆 | `#memory` |
| `50-profile.html` | 我的 | `#profile` |

## 拆分规则

- 编号十位 = 信息架构分组（0 登录 / 1 首页 / 2 对话 / 3 生活 / 4 记忆 / 5 我的）。
- 页面内按钮、返回键、底部 Tab 的跳转链接已由 `#hash` 改写为文件互跳，跳转关系与拆分前的原型一致（Tab Bar 仅出现在 4 个主 Tab 页与健康页，与原型的显隐逻辑相同）。
- 每页文件自带全部所需样式（含手机壳、状态栏、AI Orb），单文件零依赖。
- 页面右下角的「页面直达」演示导航与页脚总览 / 设计说明链接为拆分版新增，便于评审跳转；页脚的「连续原型」指向冻结存档，仅供对照。
- 设计规范与组件规格的唯一真源是 `.agents/skills/zhaoxi-design-system/`（优先级高于本目录一切文件）。
- `ai-life-agent-design.html` 保持原样，其首页按钮与页脚仍指向冻结原型，未随本次拆分改动。
