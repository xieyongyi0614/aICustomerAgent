# AICustomerServiceAgent Frontend

「角色对话 Agent」前端 —— React 调试控制台（Debug Console）：流式对话、角色状态 / 记忆 / 关系面板、LLM profile 切换与主动消息 ack。

## 技术栈

- React 19 + TypeScript + Vite
- TanStack Query（服务端状态）+ Zustand（会话 / UI 状态）
- Tailwind CSS 4 + shadcn（base-ui）+ lucide 图标
- vitest 单元测试 + msw 接口 mock

## 目录结构

```
src/
├── api/           # 传输层（chat-stream NDJSON 流解析 / rest / http / api-mode 切换）
├── app/           # 应用装配（路由 / Provider）
├── components/    # chat（对话流）/ debug（状态调试面板）/ shell（布局）/ ui（基础组件）
├── features/      # 独立功能实验位（json-viewer / token-demo）
├── hooks/         # 通用 hooks
├── stores/        # Zustand（chat-store / ui-store）
├── mocks/         # msw mock handlers（脱离后端独立开发）
├── lib/           # 工具函数
└── types/         # 共享类型
```

## 开发

```bash
npm install
npm run dev        # http://localhost:2000，/api 代理到 http://localhost:8000
```

需先启动后端（见 `apps/backend/README.md`）；无后端时可用 msw mock 模式开发（`src/api/api-mode.ts` 切换）。

## 常用脚本

| 脚本 | 说明 |
|---|---|
| `npm run dev` | 开发服务器（端口 2000，代理 `/api`） |
| `npm run build` | 类型检查 + 产物构建（`tsc -b && vite build`） |
| `npm run typecheck` | 仅类型检查 |
| `npm run lint` | eslint |
| `npm run test` | vitest 单元测试 |
| `npm run preview` | 本地预览构建产物 |

## 部署

- 本地开发代理由 `vite.config.ts` 的 `server.proxy` 配置；部署 `base` 路径用环境变量 `VITE_BASE` 调整。
- 生产部署走根目录 Docker 多阶段构建（node 构建产物 → python 后端托管 dist），一键入口为根目录 `docker compose up -d --build`（访问 `http://localhost:8020`）；三种部署方案与冒烟清单见 `docs/frontend/deploy.md`。
