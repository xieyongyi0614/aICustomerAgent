# OPS-DEPLOY-603 · 生产构建与部署挂载方案

## Task ID

OPS-DEPLOY-603

## Task Name

前端生产构建、FastAPI StaticFiles 挂载与环境变量注入方案

## Type

ARCH

## Priority

P2

## Description

让 Console 可部署：产出静态构建物并提供「同域挂载到 FastAPI」或「独立静态服务器」两条部署路径的落地方案与文档。

## Scope

- 生产构建配置：build 产物优化、base 路径可配（同域子路径挂载场景）
- 方案 A（推荐）：FastAPI StaticFiles 挂载 dist——提供 main.py 挂载示例说明与 SPA fallback（刷新非根路由回退 index.html；本应用单页面，fallback 成本极低）
- 方案 B：nginx 静态托管 + 反代 /api 到 FastAPI 的配置样例
- 环境变量生产注入约定：VITE_API_MODE 构建期固化策略（生产默认 real）、VITE_API_BASE_URL 同域缺省
- debug 端点暴露提示：部署文档注明 debug/trace 端点仅限内部网络暴露（呼应 BE-API-404 的 Permission 说明）
- README 或部署文档一页纸（放 docs/frontend/ 下，经用户确认后创建）

## Out of Scope

- CI/CD 流水线搭建
- HTTPS / 域名 / 服务器采购等运维事务
- Docker 化（如需另立任务）

## Dependencies

- 全部 P0/P1 任务完成（对可交付形态负责）

## Input

- 架构文档第 1 节（部署结论）、第 13 节 Phase 3

## Output

- 可部署构建物 + 两种方案的可执行说明 + 一页纸部署文档

## Business Rules

- 生产构建禁止包含 mock 运行时依赖被意外激活的可能（mode 固化为 real 后 mocks 不参与启动分支）
- 不引入任何密钥进前端产物

## API Dependencies

- 挂载目标：现有 FastAPI app（apps/backend）；不改其业务端点

## Data Dependencies

- 无

## Permission

- 文档层面明确：Console 与 debug 端点均按「内网工具」定位，公网暴露前必须补网关级保护

## Error Handling

- 静态资源 404 / SPA fallback 行为在两方案中分别给出验证步骤

## Acceptance Criteria

- 方案 A 本机走通：启动后端后浏览器访问即用，流式对话与 debug 端点同域可达
- base 子路径部署下刷新不 404
- 构建物体积与首屏加载数据记录在案

## Test Requirements

- 构建成功 + 挂载冒烟（真实后端一轮对话 + 打开 Trace 面板）
- 两方案各一次手工验收记录
