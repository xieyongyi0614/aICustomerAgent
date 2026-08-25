# ARCH-FE-001 · 前端工程脚手架与工程约定

## Task ID

ARCH-FE-001

## Task Name

前端工程脚手架初始化与工程约定落地

## Type

ARCH

## Priority

P0

## Description

在 `apps/frontend/` 建立 Vite + React + TypeScript 工程，落实架构文档第 11 节的目录骨架与分层红线，配置 dev 代理与环境变量约定。本任务不实现任何业务功能，产出的是一个「可启动、可扩展、约定齐全」的空应用。

## Scope

- 初始化 Vite + React + TS 工程：`apps/frontend/`，package/scripts/typecheck/lint-format 基线可用
- 接入 Tailwind CSS 与 PostCSS 配置
- 按架构文档创建目录骨架：`src/app` `src/components/{chat,debug,shell,ui}` `src/features` `src/hooks` `src/api` `src/stores` `src/types/{backend,domain}` `src/lib` `src/mocks`
- `vite.config.ts`：dev proxy 将 `/api` 转发到 `localhost:8000`
- `.env` / `.env.example`：`VITE_API_MODE=real|mock`、`VITE_API_BASE_URL` 约定与注释性说明（写在 env example 文件文本中，非代码注释）
- 路径别名（如 `@/` 指向 `src/`）
- shadcn/ui 初始化（CLI 配置文件、components.json、utils 工具位）

## Out of Scope

- 任何业务组件、页面、面板
- 设计 token 数值与主题（FE-THEME-002）
- Mock 实现（FE-MOCK-102）、传输层实现（API-FE-101）

## Dependencies

- 无（本注册表唯一无前置任务；后端泳道任务与其并行）

## Input

- `docs/frontend/frontend-architecture.md` 第 1 节（技术选型）、第 11 节（目录结构与职责红线）
- 根 `AGENTS.md` 全局约定

## Output

- 可 `npm run dev` 启动的空应用（渲染占位首页即可）
- 完整目录骨架与别名、代理、env 约定生效
- lint / typecheck 命令可执行并通过（空项目基线）

## Business Rules

- 目录职责红线自本任务起生效：`components/` 禁止出现 fetch；`api/` 不 import React；`stores/` 不发起请求；`mocks/` 只能被 `api/index.ts` 工厂引用
- 不添加代码注释，用命名表达意图
- 禁止硬编码后端地址（一律走 env / 代理）

## API Dependencies

- dev proxy 目标为本机 FastAPI（`http://localhost:8000`）；本任务只需代理配置正确，不要求后端在线

## Data Dependencies

- 无

## Permission

- 内部调试工具，无鉴权；不预留登录 UI

## Error Handling

- 后端不可达时 proxy 返回 502 属预期；本任务仅保证构建与启动不受影响，无业务错误处理逻辑

## Acceptance Criteria

- `npm run dev` 启动成功并渲染占位页；`npm run build` 与 typecheck 通过
- 路径别名在 tsconfig 与 vite 中一致生效
- dev 下请求 `/api/xxx` 被代理到 8000 端口（可用任意后端端点或 404 JSON 验证转发发生）
- `VITE_API_MODE=mock|real` 能被应用读到（临时在占位页显示当前 mode 即可，后续任务移除）
- 目录结构与注册表第 9 节引用的架构文档第 11 节一致

## Test Requirements

- 冒烟：dev 启动 + 构建通过 + typecheck 通过 + lint 通过
- 手工验证代理转发一次并记录结果于任务完成说明
