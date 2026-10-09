# 后端测试套件审核报告

- **日期**：2026-10-09
- **范围**：`apps/backend/tests/`（默认收集集 3320 用例 + legacy 3829 用例）、`apps/backend/migrations/versions/`、`docs/TESTING.md`
- **方式**：只读审核 + 本机实测（Windows / 20 逻辑核）；**未改动任何代码与配置**
- **起因**：反馈「测试有时卡死一直在跑、跑一次非常慢」，要求排查是否存在无用测试导致卡住

---

## 1. 结论摘要

1. **「无用测试导致卡死」不成立**。无用/过时用例确实存在，但全部是秒级静态扫描 / 快照类；全目录扫描确认：`while True` 0 命中（tests 下）、最大 `time.sleep` 0.05s、所有 `wait_until` 均有 10s deadline、httpx 全部指向本地 server、Redis 全部用 fakeredis、SMTP 已 mock。**不存在无界等待与真实外网调用。**
2. **卡死/超慢的主因是「并发会话 + 过度并行」**。抓到一个活体样本：某 IDE 会话以 `-n0` 跑 688 个用例（v30+v50）耗时约 13 分钟、CPU 仅消耗 68s；在隔离 worker 名下复现同一批用例只需 **96 秒**（8 倍差距）。背景：本机 `cpu_count=20`，`addopts` 的 `-n auto` 会拉起 20 个 worker 进程，多个 pytest 会话（IDE 面板 / 终端 / AI 会话）叠加时互相饿死。
3. **Windows 上的超时兜底不可靠**：`timeout_method = "thread"` 无法中断阻塞在 C 层（socket / DB 驱动 / 文件锁）的用例，真卡住时 120s 上限到了也退不出来，而 xdist 主进程没有全局看门狗 → 表现为「一直跑」。
4. 配置正常时全量并不慢：**默认收集集 3320 用例分层实测加总约 3 分钟**；`--run-legacy` 追加后 7149 用例，收集阶段 6.6s、无收集错误。

---

## 2. 实测数据（2026-10-09，本机 20 核）

| 范围 | 结果 | 耗时（pytest 内部 / 墙钟） | 最慢项 |
|---|---|---|---|
| `tests/unit` | 1591 passed | 42.9s / 47.5s | `test_feishu_boundary` 9 条各 2.2~2.4s（合计约 20s，占 unit 层近半）；`test_datetime_discipline` 6.8s |
| `tests/integration` | 428 passed / 7 skipped | 31.6s / 35.9s | `test_feishu_isolation` 8.8s、`test_evaluation_pipeline` 5.6s、3 条迁移类各 2s（setup） |
| `tests/e2e` | 182 passed | 29.9s / 34.2s | `test_chat_http_integration` 6.1s / 5.7s、cutover parity 系列 3~4.6s |
| `tests/v30+v40+v50+v51+eval+evaluation` | 1112 passed | 45.6s / 50.8s | eval gate 分钟级（其中 2 个被 `xdist_group` 串行钉住）；`test_runtime_background_cutover` 源码扫描 3s |
| **默认收集合计** | **3320 tests** | 收集 5.1s；分层加总约 3 分钟 | — |
| `--run-legacy` 收集 | **7149 tests** | 6.6s，无收集错误 | — |

结论：性能基线健康。问题不在测试内容，而在**运行环境态**（并发、超时机制、残留、并行度）。

---

## 3. 卡死/超慢根因链

### P0-1 并发会话 + `-n auto` 过度并行

- `apps/backend/pyproject.toml:63`：`addopts = "-n auto --dist loadgroup"`，本机 `os.cpu_count() = 20` → 单次运行最多 20 个 worker 进程，每个都要完整 import 应用 + 建 SQLite 连接。
- 实测活体样本（外部会话，非本次审核发起）：
  - 命令：`python -m pytest tests/v30 tests/v50 -n0 -p no:cacheprovider --basetemp=C:/tmp/pt-base-v30b -q --tb=no -rf`
  - 14:53:38 启动，约 15:06 结束（**墙钟约 13 分钟**）；12 分钟时采样 CPU 仅 67.9s、WS 243MB、7 线程。
  - 同批 688 用例隔离复现（`PYTEST_XDIST_WORKER=probe`，避开 `main.db` 争用）：**96.3s 墙钟 / 89.6s 内部，688 passed**。
  - 差异来源：当时本机同时存在多组进程（pylint LSP ×2、black LSP ×2 常驻，另有其他 pytest 会话），20 worker 的会话把 CPU/IO 抢占殆尽。
- **自查命令**：
  ```powershell
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*pytest*" } | Select-Object ProcessId,CreationDate,CommandLine
  ```

### P0-2 `pytest-timeout` thread 模式对 C 层阻塞无效

- `apps/backend/pyproject.toml:66-67`：`timeout = 120` / `timeout_method = "thread"`。
- thread 方法通过向主线程注入异常实现超时，仅能在 Python 字节码执行点生效；阻塞在 socket 收包、PSYCOPG 等 C 层等待、Windows 文件锁时不会中断。
- xdist 主进程没有全局看门狗：worker 卡住且超时注入无效时，整个会话表现为「一直在跑」。
- 对照：`docs/TESTING.md:120` 声称「任何用例卡死 120s 后被强制失败并 dump 全线程栈，不再无限等待」——该承诺在 C 层阻塞场景下不成立，应修订措辞或补看门狗。
- **卡死现场取证**：建议安装 `py-spy`（`.venv\Scripts\pip install py-spy`），卡住时执行 `py-spy dump --pid <PID>` 直接抓栈。

### P1-1 每用例固定开销（连纯 unit 用例也要建 57 张表）

- `apps/backend/tests/conftest.py` 的 autouse `_offline_repos`：每个用例执行 `Base.metadata.drop_all(engine)` + `create_all(engine)`（`conftest.py:402-404`），teardown 另有后台任务等待最多 2s（`conftest.py:409-414`）与 `engine.dispose()`（`conftest.py:419`）。
- 表数量：`tests/support/schema_pins.py` 冻结 `SCHEMA_TABLE_COUNT = 57` → 每用例约 114 次 DDL，3320 用例即约 38 万次 DDL。
- 影响：`tests/unit` 内约 1448 个用例中大量纯逻辑用例（如 router/chain 单测）同样付出建表成本，是 unit 层时间的主要构成。

### P1-2 潜在挂起源（结构性，尚未触发）

- **未登记 `SessionLocal` 的新模块会连 `.env` 真实 PostgreSQL**（历史「根因B」模式）：
  - 覆盖机制为人工清单：`conftest.py:126-194` 的 `_REPO_MODULES` / `_SERVICE_DB_MODULES`。
  - 本次核对：全 `app/` 下含 `SessionLocal` 的模块 69 个 —— `repositories/*`（38）全覆盖；services 侧 memory(9)/relationship(3)/reflection(7)/development(6)/insights(1) 均在清单；`app/services/tool/confirmation.py`、`permission.py` 仅文档串提及，无实际绑定；`app/services/reflection/evidence/__init__.py` 为纯 re-export（docstring 明示打桩目标为 `collectors`）。
  - **当前无泄漏**，但清单靠人工维护，`docs/TESTING.md:121` 亦以纪律形式警告。建议增加「清单差集自动校验」测试。
- **Redis 客户端无连接/命令超时**：`app/core/redis_client.py:25` 的 `from_url(url, decode_responses=True)` 未设 `socket_connect_timeout` / `socket_timeout`；`app/main.py:68-74` 的 lifespan 首屏就 `await ping_redis()`。当前 `.env` 指向 `redis://127.0.0.1:6379/0`（本机拒绝连接=快速失败），但若指向不可达主机（防火墙 DROP），`with TestClient(app)` 类用例将永久挂起且 120s 超时救不回来。
- **迁移类测试**：`tests/integration/test_db_migration.py:64-66`、`test_relationship_migration.py:61`、`test_channel_identity.py:299`、`test_scene_repository.py:75` 均执行完整 `command.upgrade(cfg, "head")`（0001 为折叠 58 个版本的大迁移）；PG 可达时真连 `asuna_test` 升降级（已用 `xdist_group("migration")` 串行保护）。单条 1~2s，属可接受的慢点，但需知晓 PG 实例状态会显著影响耗时。

### P2-1 残留离线库与被强杀会话

- `conftest.py:380-385` 仅在 `pytest_sessionfinish` 清理 `.tmp/offline-db/{worker}.db`；会话被强杀（IDE 停止按钮 / 超时失败后手动终止）时残留。
- 实测会话进行中观察到 `main.db`（925KB）+ `main.db-wal`（4.1MB）长期驻留；正常退出后可被清空。
- 残留脏库会让下一次 `-n0` 运行先在大 WAL 库上 `drop_all`，进一步放大「第一次特别慢」的观感。
- 建议：`pytest_sessionstart` 先清理残留（`conftest.py` 增加钩子）。

### P2-2 `slow` 默认未排除、约定与配置不一致

- `pyproject.toml:63` 的 `addopts` 未包含 `-m "not slow"`；`docs/TESTING.md:130` 的 CI `backend` job 才显式排除。
- 本地直接 `pytest` 会连带跑 SSE server / lifespan 类慢测（`conftest.py:578-603` 的 `SLOW_TEST_FILES`），与「slow 日常排除」的文档约定不符。
- 另注意 `tests/e2e/test_v5_matrix.py` 使用 TestClient 全链路但**未**登记进 `SLOW_TEST_FILES`（同类 `test_v65_matrix.py` 已登记），存在遗漏。

---

## 4. 无用/过时测试清单

### 4.1 默认收集集内（按优先级）

| # | 位置 | 问题（含证据） | 建议 |
|---|---|---|---|
| 1 | `tests/v40/test_life_ownership_integration.py:122-136` | `BACKEND_ROOT = Path(__file__).resolve().parents[3]`（`:13`）算错一层（应为 `[2]`）→ cwd = `apps/`，pathspec `apps/backend/app/services/world` 解析为不存在的路径，**断言恒真**；实测 `cd apps; git diff --stat -- apps/backend/app/services/world` 输出为空且 exitcode=0，连 returncode 也挡不住；另引入无 timeout 的 git 子进程 | **删除**；若保留门禁：修 `parents[2]` + `--relative` + 断言 returncode + 迁 CI 独立 job |
| 2 | `tests/unit/test_v2_memory_settings.py:15-20` | **零断言空用例**：`test_v2_memory_flags_env_overridable` 无任何 assert、`monkeypatch` 未使用，只两次 `cache_clear()` | 删除该用例 |
| 3 | `tests/unit/test_feishu_boundary.py:269-274` | 8 条参数化每条都重跑整遍 AST 扫描再过滤，而 `:185-187` 已断言 `violations == []` → 信息量为 0；`_scan_core()` 被调用约 11 次，是本文件 ~20s 开销的主因（unit 层最慢） | 删除 8 条冗余；或给 `_scan_core` 加缓存 |
| 4 | `tests/v40/test_runtime_background_cutover.py:106-170` | 版本契约类冻结：开关集合比大小（`:167-170` + `tests/v40/support.py:21-50` 的 `V30_ENABLED_FLAGS`）、默认值（`:164-165`）、「六段仍为影子」（`:159-162`）、rglob 全库找函数名（`:121-129`）——与 `docs/TESTING.md:159-161` 已删的「开关快照/冻结断言」同类，下一版本合法演进必假红 | `:178-248` 行为等价性保留；`:106-170` 迁 CI 独立架构守卫 job |
| 5 | `tests/v50/test_design_principles.py:12-37` | 后端以 CWD 相对路径 `Path("../mobile/...")` 静态扫 Flutter 源码（`index()` 顺序比较）+ 文案字面量，跨工程耦合；Flutter 侧重命名/改文案即红 | 迁 mobile 侧测试或 CI 独立 job |
| 6 | `tests/v51/test_ledger_pending_api.py:227-237` 与 `tests/v51/test_ledger_stats_api.py:195-204` | 同一断言（ledger API 零 repositories import）重复两处，且检查集合不一致（一处含 `app.core.db`，一处不含） | 合并为 1 条架构守卫 |
| 7 | `tests/e2e/test_v65_matrix.py:49-51` 与 `:74-76` | 两条用例断言完全相同（均只断言 `behavior.degraded is False`），近乎恒真、重复 | 删 1 条 |
| 8 | `tests/unit/test_inventory_grounding_acceptance.py:89-100`、`:84-86` | `if report.has_conflict:` 条件式断言 → 无冲突时空过；`:84-86` 与 `:78-82` 用例重叠；用例编号（Acceptance 1~6）对应的一批开关已于 2026-09-28 固化删除，编号已无版本含义 | 去条件断言、删重复、清理过时编号 |
| 9 | `tests/unit/test_acceptance_temporal_fix.py:42-93` | 自然语言整句冻结（含 `"用户在09月02日完成了用户的面试"` 这类病句一起钉住） | 改为关键要素断言（日期 + 语义键） |
| 10 | `tests/eval/` 三个 gate 写仓库目录 | `test_development_growth_loop.py:166-172`、`test_relationship_eval_gate.py:38-44`、`test_memory_eval_gate.py:477-481` 把报告写进 `tests/eval/reports/`，且 `mem-*.json`、`rel-*.json`、`dev-growth-*.json` **生成物已入库**；2 个文件被 `xdist_group` 串行钉住 | 报告改 `tmp_path`；gate 迁 CI 独立 job |
| 11 | `tests/eval/test_memory_eval_gate.py:7-8`、`tests/eval/test_relationship_eval_gate.py:23-26,53` | docstring 引用 `tests/golden` 的 `prompt_snapshots`（该目录实际只有 4 份 `prompt_*.txt` 快照，无 `prompt_snapshots`）；`rel_eval_flags` 为死夹具；用例名仍叫 `flag_off`（对应开关已随版本门控体系删除） | 修文档串与命名 |

### 4.2 legacy 与文档侧

- `tests/v2`、`v8.5`、`v22~v26`（3829 用例）：已在 `docs/TESTING.md:147-163` 登记为保留、默认不收集，`--run-legacy` 收集无错误。**状态正确，不属"无用"**；其中 v24（1011）、v25（1142）体量最大，可评估二次瘦身。
- 版本测试文档（`docs/version/v1.0.0/v5/testing.md`、`v6.5/testing.md` 等）保留原文属有意为之（TESTING.md §9：视为当时的记录）。
- 需注意的文档漂移点：
  - `docs/TESTING.md:120` 的「超时不再无限等待」承诺与 thread 模式的实际能力不符（见 3 节 P0-2）。
  - `docs/TESTING.md:130` 约定 slow 日常排除，但配置层未默认排除（见 P2-2）。
  - `tests/eval/test_memory_eval_gate.py:7-8` 引用了不存在的 `tests/golden/prompt_snapshots`。

---

## 5. 修复建议（按性价比排序）

1. **运行纪律（立刻见效，零风险）**
   - 同一时刻只允许一个 pytest 会话（含 AI 会话、IDE 测试面板、终端）。
   - 日常用 `-m "not slow"`；Windows 上把 `-n auto` 改为固定 `-n 8`（20 worker 在 Windows 文件 IO + LSP 常驻进程下边际收益为负）。
   - 出现「卡死」时先用第 3 节的自查命令确认是否存在并发会话。
2. **conftest 增强**：新增 `pytest_sessionstart` 清理 `.tmp/offline-db/` 残留，防强杀脏库。
3. **消除潜在挂起**：
   - `app/core/redis_client.py:25` 增加 `socket_connect_timeout=1, socket_timeout=1`（或 lifespan 的 `ping_redis` 包 `asyncio.wait_for`）。
   - 为 `_SERVICE_DB_MODULES` 清单增加自动差集校验（扫描 `from app.core.db import ... SessionLocal` 的模块，漏登记即失败），把人工纪律变成测试。
4. **清理无用用例**：按 4.1 表逐批处理（建议顺序：1→2→3→6→7→8，再评估 4/5/9/10/11）；AST 扫描加缓存可再省 unit 层约 25s。
5. **测试时长治理（可选）**：
   - `_offline_repos` 惰性化，纯逻辑 unit 用例不建 57 张表（收益最大，改动需谨慎）。
   - 迁移一致性类测试若嫌慢，可评估「单点 digest（`tests/support/schema_pins.py`）+ heads 校验」替代每次全链 upgrade。
   - 给 `tests/e2e/test_v5_matrix.py` 补 `slow` 登记，保持与 `test_v65_matrix.py` 一致。

---

## 6. 附录

### 6.1 复现本报告数据的关键命令

```powershell
# 分层实测
cd apps/backend
.venv\Scripts\python.exe -m pytest tests/unit -q --durations=25 -p no:cacheprovider
.venv\Scripts\python.exe -m pytest tests/integration -q --durations=30 -p no:cacheprovider
.venv\Scripts\python.exe -m pytest tests/e2e -q --durations=30 -p no:cacheprovider
.venv\Scripts\python.exe -m pytest tests/v30 tests/v40 tests/v50 tests/v51 tests/eval tests/evaluation -q --durations=30 -p no:cacheprovider

# 全量规模与 legacy 可收集性
.venv\Scripts\python.exe -m pytest --collect-only -q          # 3320
.venv\Scripts\python.exe -m pytest --collect-only --run-legacy -q   # 7149
```

### 6.2 隔离复现单进程耗时（避免与其他会话争抢 `main.db`）

```powershell
$env:PYTEST_XDIST_WORKER="probe"   # 使 offline-db 使用 probe.db 而非 main.db
.venv\Scripts\python.exe -m pytest tests/v30 tests/v50 -n0 -q -p no:cacheprovider
```

### 6.3 卡死现场诊断

```powershell
# 1) 确认是否有并发 pytest 会话
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*pytest*" } | Select-Object ProcessId,CreationDate,CommandLine

# 2) CPU 采样：6s 内 CPU 不增长 = 阻塞而非在算
$a=Get-Process -Id <PID>; Start-Sleep 6; $b=Get-Process -Id <PID>; "$($b.CPU - $a.CPU)s per 6s"

# 3) 线程栈（推荐）
pip install py-spy
py-spy dump --pid <PID>
```

---

*本报告为只读审核产物；文中所有耗时、用例数、进程状态均为 2026-10-09 本机实测。*
