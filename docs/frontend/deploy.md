# Debug Console 部署指南（OPS-DEPLOY-603）

> 定位：内网开发者工具。Console 与后端 debug 端点（`/api/v1/debug/**`、`/api/v1/state`）**仅限内网暴露**；公网部署前必须加网关级保护（Basic Auth / IP 白名单 / mTLS）。

## 构建产物

```powershell
cd apps/frontend
npm run build          # 产出 dist/（base 默认 '/'，子路径挂载时设 VITE_BASE 或改 build.base）
```

环境变量在构建期固化：

| 变量 | 生产取值 | 说明 |
|---|---|---|
| `VITE_API_MODE` | `real`（默认缺省即 real） | mock 分支运行时不会激活 |
| `VITE_API_BASE_URL` | 留空 | 同域部署走相对路径 `/api` |
| `VITE_BASE` | `/` | 子路径挂载时与挂载前缀一致，如 `/console/` |

构建产物体积（2026-08-26 实测，vite 6.4.3）：

| 类别 | 文件 | 原始 | gzip |
|---|---|---|---|
| 首屏 JS | `index-[hash].js` | 457.92 kB | 147.16 kB |
| 首屏 JS | `vendor-query-[hash].js` | 47.37 kB | 14.75 kB |
| 首屏 JS | `vendor-react-[hash].js` | 3.90 kB | 1.52 kB |
| 首屏 CSS | `index-[hash].css` | 76.85 kB | 13.63 kB |
| 懒加载 | `isObject-[hash].js`（JsonViewer 依赖） | 183.90 kB | 65.67 kB |
| 懒加载 | `index-[hash].js`（次级 chunk） | 95.37 kB | 26.34 kB |
| 懒加载 | `msw-handlers-[hash].js` | 19.18 kB | 7.58 kB |

**首屏合计 ≈ 586 kB（gzip ≈ 177 kB）+ index.html 0.57 kB**。

## 方案 A（推荐）：FastAPI StaticFiles 同域挂载

参考实现已提供：`apps/backend/scripts/serve_with_frontend.py`（挂载 `dist/assets` + SPA fallback）。

```powershell
cd apps/backend
uv run python scripts/serve_with_frontend.py 8020            # 根路径挂载
uv run python scripts/serve_with_frontend.py 8020 console    # 子路径挂载（需先以 VITE_BASE=/console/ 构建）
# 浏览器 http://127.0.0.1:8020 → Console 与 /api 同域，无需 CORS
```

接入正式后端时等价做法：把脚本中的两段挂载代码复制进 `app/main.py`（放在 API 路由注册之后），或用 nginx 承担静态层（方案 B）。

SPA fallback 说明：catch-all GET 仅在**所有 API 路由之后**注册，非文件路径一律回退 `index.html`，刷新不 404。

## 方案 B：nginx 静态托管 + 反代

```nginx
server {
    listen 80;
    root /srv/asuna-console;            # apps/frontend/dist
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_buffering off;             # NDJSON 流式必须关闭缓冲
        proxy_read_timeout 300s;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

`proxy_buffering off` 是流式回答的关键配置，缺失会导致前端整段等待。

## 方案 C：Docker 一体化部署（已验证）

仓库根目录提供 `Dockerfile`（多阶段：node:22 构建前端 → python:3.13-slim 运行后端并托管 dist）与 `docker-compose.yml`（console + postgres:16）。

```powershell
# 前置：apps/backend/.env 至少含 OPENAI_API_KEY / BASE_URL / MODEL（数据库地址由 compose 覆盖为 postgres 服务）
docker compose up -d --build
# 浏览器 http://localhost:8020 → Console 与 /api 同域
docker compose down          # 停止（数据卷 asuna_pgdata 保留）
```

要点：

- 容器启动自动执行 `alembic upgrade head`（0001 → 0002），无需手工迁移
- 静态托管复用 `scripts/serve_with_frontend.py`，经 `FRONTEND_DIST_DIR=/srv/frontend/dist`、`CONSOLE_HOST=0.0.0.0` 环境变量适配容器；本机直跑行为不变
- 构建参数 `--build-arg VITE_API_MODE=real VITE_BASE=/` 可覆盖前端构建期环境变量，默认即生产取值
- 密钥不进镜像：`.dockerignore` 排除 `.env`，LLM 配置经 compose `env_file` 运行时注入

## 冒烟清单

对话链路以 FakeLLM 注入的完整 FastAPI 应用复验（仓库约定：禁真实 LLM）；浏览器 UI 走查由开发会话人工完成。

方案 A（根路径 + `/console/` 子路径各一次）：

- [x] `GET /` 返回 index.html（200 text/html）
- [x] `GET /assets/*.js` 200（457,920 字节主 chunk）
- [x] `GET /health` 返回 `{"status":"ok"}`
- [x] 同域 `POST /api/v1/chat/message` 流式返回 `turn_meta` → `delta` → `done`（含 `turn_id`）与 `X-Session-Id`
- [x] 同域 `GET /api/v1/state`、`GET /api/v1/debug/turns/{turn_id}/trace` 均 200
- [x] 刷新任意路径不 404（含子路径模式 `/console/xxx` 深链）
- [x] 子路径模式下 index.html 引用与 assets 均带 `/console/` 前缀且可达

方案 B：nginx 配置样例供部署时按样例自验（`try_files` 回退 + `proxy_buffering off`），本机无 nginx 环境未实测。

方案 C（Docker，2026-08-26 实测）：

- [x] `docker compose up -d --build` 一键起 postgres + console，console 健康检查通过
- [x] 容器内 alembic 自动迁移 0001 → 0002 成功（PostgreSQL 方言）
- [x] `GET /health`、`GET /`、`GET /assets/*.js`、`GET /api/v1/state` 经宿主机端口映射均 200
- [ ] 流式对话走真实 LLM 未在容器内复测（避免消耗外部配额；流式契约已在本机 FakeLLM 冒烟覆盖，容器仅改变打包方式）

## 已知边界

- 主 chunk 458 kB（gzip 147 kB）：内网工具可接受；如需优化走面板懒加载，见 FE-POLISH 记录
- trace 数据为后端内存 LRU（默认 20 轮），后端重启即清空
