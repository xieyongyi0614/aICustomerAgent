import os
import re
import time
from pathlib import Path
from typing import Any

# 测试进程强制离线：系统代理（Windows 注册表层，env 不可见）会把 LLM 调用与
# localhost HTTP 一起路由进代理客户端，代理未运行时全部挂起（TLS 黑洞）。
# NO_PROXY=* 使 urllib/httpx 忽略注册表代理；测试 profile 本就指向不可达假端点，
# 期望快速连接失败而非挂起。仅影响 pytest 进程，不改变开发/运行环境的代理行为。
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("https_proxy", None)
os.environ.setdefault("OPENAI_API_KEY", "test")
# 世界/lifespan 循环的 DB 访问已由 autouse _offline_repos 落到内存 SQLite，无需再关闭 world。
os.environ.setdefault(
    "LLM_PROFILES_JSON",
    '[{"id":"longcat","label":"LongCat (test)","base_url":"https://example.invalid/v1","model":"fake","api_key":"test"}]',
)
os.environ.setdefault("DEFAULT_LLM_PROFILE", "longcat")

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableLambda
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api.v1.deps import get_chat_llm
from app.core import llm_factory
from app.application import chat_pipeline as agent_service
from app.services.relationship import evaluation as relationship_evaluation_service
from app.services.relationship import narrative as relationship_narrative_service
from app.services.relationship import patterns as relationship_patterns_service
from app.services.memory import attribution as memory_attribution
from app.services.memory import commands as memory_commands
from app.services.memory import evaluator as memory_evaluator
from app.services.memory import ingest as memory_ingest
from app.services.memory import job_worker as memory_job_worker
from app.services.memory import lifecycle as memory_lifecycle
from app.services.memory import product_view as memory_product_view
from app.services.memory import retriever as memory_retriever
from app.services.development import evolution as evolution_service
from app.services.development import aggregate as development_aggregate
from app.services.development import audit as development_audit
from app.services.development import attribution as development_attribution
from app.services.development import evaluation as development_evaluation
from app.services.development import policy as development_policy
from app.services.reflection import attribution as reflection_attribution
from app.services.insights import query as insights_query
from app.services.reflection.evidence import collectors as reflection_evidence
from app.services.reflection import evaluation as reflection_evaluation
from app.services.reflection import lifecycle as reflection_lifecycle
from app.services.reflection import reflector as reflection_reflector
from app.services.reflection import tool_feed as reflection_tool_feed
from app.services.reflection import triggers as reflection_triggers
from app.core.db import Base
from app.core.settings import get_settings

# `app.main` 在模块级 import 会连带拉入整个 FastAPI 应用（全部 router + LangChain +
# OpenAI SDK），每个 xdist worker 白付约 3.8s；而 3300+ 用例里只有 3 个 fixture 需要
# app 对象（llm_override / _default_auth_user / use_auth_user）。故改为惰性取值，
# 让纯逻辑用例完全不付这笔启动开销。
# 注：main.py 无模块级注册副作用（register_* 全在 lifespan 内），故延迟导入安全。
_APP = None

# 内部标记：标注「会加载 FastAPI 应用（app.main）因而需要 auth override」的用例。
# 由 `pytest_collection_modifyitems` 按「用例所在模块是否 import app.main」自动打标，
# 供 autouse `_default_auth_user` 决定是否安装 dependency override。
_APP_BASED_MARKER = "app_based"


def _get_app():
    """惰性取 FastAPI 应用单例（首次调用触发 app.main 导入并缓存）。"""
    global _APP
    if _APP is None:
        from app.main import app as _app_instance

        _APP = _app_instance
    return _APP

from app.application import action_engine as _action_engine_impl
from app.application import autonomy_bridge as _autonomy_bridge_impl
from app.application import observability as _observability_impl
from app.application import world_engine as _world_engine_impl
from app.application.worker_loop import run_worker_loop as _run_worker_loop_impl
from app.services.action import port as _action_port
from app.services.autonomy import port as _autonomy_port
from app.services.memory import job_worker as _memory_job_worker
from app.services.observability import port as _observability_port
from app.services.world import engine_port as _world_port

_action_port.register_action_engine(_action_engine_impl)
_observability_port.register_observability(_observability_impl)
_world_port.register_world_engine(_world_engine_impl)
_autonomy_port.register_autonomy_bridge(_autonomy_bridge_impl)
_memory_job_worker.register_worker_loop(_run_worker_loop_impl)

from app.repositories import (
    action_repository,
    agent_metric_repository,
    agent_state_snapshot_repository,
    app_release_repository,
    background_job_repository,
    briefing_preference_repository,
    car_repository,
    character_state_repository,
    channel_identity_repository,
    conversation_repository,
    decision_repository,
    development_change_repository,
    emotion_history_repository,
    evaluation_repository,
    feishu_dedupe_ledger_repository,
    feishu_delivery_ledger_repository,
    goal_repository,
    ledger_repository,
    life_task_repository,
    llm_call_repository,
    loop_run_repository,
    memory_repository,
    outbox_repository,
    personality_state_repository,
    proactive_repository,
    prompt_snapshot_repository,
    relationship_conflict_repository,
    relationship_event_repository,
    relationship_milestone_repository,
    relationship_repository,
    relationship_snapshot_repository,
    scene_state_repository,
    summary_repository,
    trace_repository,
    trigger_registry_repository,
    user_repository,
    world_repository,
    world_simulation_repository,
)

WAIT_TIMEOUT = float(os.environ.get("E2E_WAIT_TIMEOUT", "10.0"))

_REPO_MODULES = (
    action_repository,
    background_job_repository,
    briefing_preference_repository,
    channel_identity_repository,
    feishu_dedupe_ledger_repository,
    feishu_delivery_ledger_repository,
    conversation_repository,
    summary_repository,
    memory_repository,
    character_state_repository,
    relationship_repository,
    relationship_event_repository,
    emotion_history_repository,
    scene_state_repository,
    goal_repository,
    proactive_repository,
    evaluation_repository,
    trace_repository,
    trigger_registry_repository,
    loop_run_repository,
    agent_state_snapshot_repository,
    agent_metric_repository,
    outbox_repository,
    personality_state_repository,
    llm_call_repository,
    prompt_snapshot_repository,
    decision_repository,
    development_change_repository,
    world_repository,
    world_simulation_repository,
    relationship_milestone_repository,
    relationship_conflict_repository,
    relationship_snapshot_repository,
    user_repository,
    ledger_repository,
    life_task_repository,
    car_repository,
    app_release_repository,
)

_SERVICE_DB_MODULES = (
    memory_attribution,
    memory_commands,
    memory_evaluator,
    memory_ingest,
    memory_job_worker,
    memory_lifecycle,
    memory_product_view,
    relationship_evaluation_service,
    relationship_narrative_service,
    relationship_patterns_service,
    memory_retriever,
    reflection_attribution,
    reflection_evidence,
    reflection_evaluation,
    reflection_lifecycle,
    reflection_reflector,
    reflection_tool_feed,
    reflection_triggers,
    development_aggregate,
    development_policy,
    development_audit,
    development_attribution,
    development_evaluation,
    evolution_service,
    insights_query,
)


def chat_post_process_tasks():
    from app.application import post_process

    return post_process.background_tasks


def observability_tasks():
    from app.application import observability

    return observability.background_tasks


def wait_until(predicate, timeout=None):
    deadline = time.time() + (timeout or WAIT_TIMEOUT)
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


class FakeLLM(BaseChatModel):
    response: Any = ""
    structured_responses: dict[str, Any] = None
    structured_errors: dict[str, Exception] = None
    raise_exc: Exception | None = None
    seen_messages: list = []

    def __init__(
        self,
        response="",
        structured_responses=None,
        raise_exc=None,
        structured_errors=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.response = response
        self.structured_responses = structured_responses or {}
        self.raise_exc = raise_exc
        self.structured_errors = structured_errors or {}
        self.seen_messages = []

    def with_structured_output(self, schema, **kwargs):
        def _resolve(inputs):
            self.seen_messages.append([inputs])
            if self.raise_exc:
                raise self.raise_exc
            error = self.structured_errors.get(schema.__name__)
            if error is not None:
                raise error
            data = self.structured_responses.get(schema.__name__)
            if isinstance(data, dict):
                return schema.model_validate(data)
            return data

        return RunnableLambda(_resolve)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.raise_exc:
            raise self.raise_exc
        self.seen_messages.append(list(messages))
        text = self.response if isinstance(self.response, str) else "".join(self.response)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        if self.raise_exc:
            raise self.raise_exc
        self.seen_messages.append(list(messages))
        chunks = self.response if isinstance(self.response, list) else [self.response]
        for chunk in chunks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=chunk))

    @property
    def _llm_type(self):
        return "fake"


@pytest.fixture
def fake_llm():
    return FakeLLM


@pytest.fixture(autouse=True)
def _reset_llm():
    yield
    llm_factory.reset_llm()


@pytest.fixture
def llm_override():
    def _apply(llm):
        _get_app().dependency_overrides[get_chat_llm] = lambda: llm
        return llm

    yield _apply
    _get_app().dependency_overrides.pop(get_chat_llm, None)


@pytest.fixture(autouse=True)
def _default_channel_gate_off(monkeypatch):
    """Autouse：默认档钉住频道总闸 off，隔离真实 .env 的 FEISHU_ENABLED 值。

    channel 工具的 registry 状态用例依赖默认关闭档；显式 override_settings
    的用例在本夹具之后应用，不受影响。
    """
    monkeypatch.setenv("FEISHU_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


TEST_USER_ID = "default-user"
"""测试身份：产品端点经 `require_user` 注入的 user_id（生产无默认用户概念）。

取值沿用历史字面量，以免 ~300 处世界域 / 后台域夹具连锁改写（`home:default-user`
这类派生 world_id 亦随之变动）——那是纯改名 churn，与本次「退役默认用户概念」无关。
"""


@pytest.fixture(autouse=True)
def _default_auth_user(request):
    """产品端点 user_id 收口自 require_user（v5.0.0 §14 / ADR 13）。

    HTTP 测试统一以 `TEST_USER_ID` 直连，免除逐用例造令牌；需切换身份的用例用
    `use_auth_user`；鉴权语义专项用例（tests/v50/test_identity_cutover.py）在用例内
    pop 掉本 override 走真实解析。

    仅对**确实会加载 FastAPI 应用**的用例安装 override（见
    `_APP_BASED_MARKER`）：其余纯逻辑用例跳过，从而完全不触发 `app.main` 的
    重型导入（约 3.8s/进程）。未加载应用的用例本就不会经 ASGI 发请求，
    override 对其无意义。
    """
    if request.node.get_closest_marker(_APP_BASED_MARKER) is None:
        yield
        return

    from app.api.v1 import auth as auth_api

    _get_app().dependency_overrides[auth_api.require_user] = lambda: TEST_USER_ID
    yield
    _get_app().dependency_overrides.pop(auth_api.require_user, None)


def use_auth_user(user_id: str) -> None:
    """把 require_user override 切到指定 user_id（测试辅助，fixture / helper 均可调）。

    每个用例开始时由 autouse `_default_auth_user` 重置为 `TEST_USER_ID`，故用例内
    切换无需自行还原。
    """
    from app.api.v1 import auth as auth_api

    _get_app().dependency_overrides[auth_api.require_user] = lambda: user_id


_OFFLINE_DB_DIR = Path(__file__).resolve().parent.parent / ".tmp" / "offline-db"
_OFFLINE_ENGINES: dict[str, Any] = {}


def _offline_engine():
    """xdist worker 级复用引擎：文件库 + 连接池 + WAL（每 Session 独立连接）。

    早期用 `sqlite://` + StaticPool 让全进程共用一条连接，用例内的
    `asyncio.to_thread` / TestClient portal 线程 / 用例线程并发时互相踩踏事务与
    identity map（`Could not refresh instance`、丢行、时序抖动），并发用例在 xdist
    负载下随机红。改为 worker 级文件库后由 SQLite 自身序列化写入（busy_timeout 兜底），
    且不产生每测试一个临时文件（避免 pytest tmp 目录膨胀）。
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    engine = _OFFLINE_ENGINES.get(worker)
    if engine is None:
        from app.core.db.engine import json_serializer

        _OFFLINE_DB_DIR.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            f"sqlite:///{(_OFFLINE_DB_DIR / f'{worker}.db').as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 30},
            json_serializer=json_serializer,
        )

        @event.listens_for(engine, "connect")
        def _sqlite_concurrency_pragmas(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=OFF")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        _OFFLINE_ENGINES[worker] = engine
    return engine


def pytest_sessionfinish(session, exitstatus):
    for worker, engine in list(_OFFLINE_ENGINES.items()):
        engine.dispose()
        for suffix in ("", "-wal", "-shm"):
            (_OFFLINE_DB_DIR / f"{worker}.db{suffix}").unlink(missing_ok=True)
    _OFFLINE_ENGINES.clear()


@pytest.fixture(autouse=True)
def _offline_repos(monkeypatch):
    """Autouse：除显式 TEST_USE_POSTGRES=1 外，把所有 repo 与 memory 服务的 SessionLocal 指向离线 SQLite。

    修复根因B：PromptBuilder.build(analysis=...) 等“纯单测”隐含访问
    relationship_milestone_repository.SessionLocal，若不替换则连真实 PostgreSQL(.env) 而挂起。
    services 层新增模块级 SessionLocal 的模块必须同步加入 _SERVICE_DB_MODULES。

    隔离：worker 级文件库（`_offline_engine`，每 Session 独立连接），每测试
    `drop_all + create_all` 重建表；测试间不共享内存状态。
    """
    if os.environ.get("TEST_USE_POSTGRES") == "1":
        yield None
        return
    engine = _offline_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in (*_REPO_MODULES, *_SERVICE_DB_MODULES):
        monkeypatch.setattr(module, "SessionLocal", testing_session)
    yield testing_session
    deadline = time.time() + 2.0
    while (
        (agent_service.background_tasks or chat_post_process_tasks() or observability_tasks())
        and time.time() < deadline
    ):
        time.sleep(0.02)

    from app.application import post_process as chat_post_process

    chat_post_process.reset_user_write_locks()
    engine.dispose()


@pytest.fixture(autouse=True)
def _persistent_outbound_idempotency():
    """Autouse：与生产一致地安装出站幂等持久化实现。

    生产由 `app/main.py` 在 `FEISHU_ENABLED` 时**无条件安装**（出站幂等是必需能力，
    没有开关）。测试里必须同样安装，否则 `delivery` 会走「hook 未安装」的降级路径
    （放行发送），幂等用例会失去意义。`_offline_repos` 已把仓储的 SessionLocal 指向
    内存 SQLite，故这里装的就是真实实现。
    """
    from app.channels.feishu import delivery
    from app.services.delivery import ledger as feishu_delivery_ledger_service

    delivery.set_persistent_idempotency(
        feishu_delivery_ledger_service.claim,
        feishu_delivery_ledger_service.release,
    )
    yield
    delivery.clear_persistent_idempotency()


@pytest.fixture
def db_session_factory(_offline_repos):
    return _offline_repos


def _known_env_keys() -> frozenset:
    """settings 字段名大写即环境变量名（`_shared.py` 无 `env_prefix` / alias 层）。"""
    from app.core.settings import Settings

    return frozenset(name.upper() for name in Settings.model_fields)


_VERSIONED_ENV_KEY = re.compile(r"^V[0-9]+_")


def set_known_env(monkeypatch, env_key: str, value) -> None:
    """写入环境变量前校验其对应真实 settings 字段。

    字段改名后旧 env 名会被 `extra="ignore"` 静默吞掉：用例照常通过，闸门却没开。
    这里把那种静默失效改成显式失败——改名时必须同步改调用点，而不是让断言假通过。
    """
    if env_key.upper() not in _known_env_keys():
        raise AssertionError(
            f"未知设置项 {env_key}：不对应任何 settings 字段，"
            "环境变量名 = 字段名大写（字段是否已改名？）"
        )
    monkeypatch.setenv(env_key, str(value))


def set_known_flag_env(monkeypatch, env_key: str, value) -> None:
    """写入环境变量；仅对形如 `V<数字>_` 的版本化键校验字段存在。

    `v24_tool_env` 除开关外还用于注入外部工具密钥（如
    `EXT_API_WEATHER_TOKEN`）这类非 settings 字段的环境变量，故只守卫会被改名
    影响的版本化键，其余原样放行。

    去前缀重构（轨道 A）后测试中已无版本化键，本分支实际处于休眠状态；保留它是为了
    让「旧 env 名残留」这类回归仍能在写入点被拦住。
    """
    if _VERSIONED_ENV_KEY.match(env_key.upper()):
        set_known_env(monkeypatch, env_key, value)
    else:
        monkeypatch.setenv(env_key, str(value))


@pytest.fixture(autouse=True)
def _pin_test_settings_baseline(monkeypatch):
    """部署侧 `.env` 不得改变测试基线：演绎段注入固定开启（用例内可显式覆盖）。

    该策略位整体改写回答链 prompt，golden / answer 用例都按「开启」写死；
    在测试进程里先钉住它，避免本机 `.env` 取 false 时出现「只有我的机器红」。
    """
    set_known_env(monkeypatch, "ROLEPLAY_PROMPT_MODE", "full")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def override_settings(monkeypatch):
    def _apply(**kwargs):
        env_map = {
            "summary_threshold": "SUMMARY_THRESHOLD",
            "router_confidence_threshold": "ROUTER_CONFIDENCE_THRESHOLD",
            "memory_importance_threshold": "MEMORY_IMPORTANCE_THRESHOLD",
            "memory_top_k": "MEMORY_TOP_K",
            "conversation_max_messages": "CONVERSATION_MAX_MESSAGES",
            "conversation_max_chars": "CONVERSATION_MAX_CHARS",
            "energy_turn_decay": "ENERGY_TURN_DECAY",
            "energy_reset_hours": "ENERGY_RESET_HOURS",
            "stage_friend_familiarity": "STAGE_FRIEND_FAMILIARITY",
            "stage_close_intimacy": "STAGE_CLOSE_INTIMACY",
            "stage_close_trust": "STAGE_CLOSE_TRUST",
            "stage_partner_intimacy": "STAGE_PARTNER_INTIMACY",
            "stage_partner_trust": "STAGE_PARTNER_TRUST",
        "trace_capacity": "TRACE_CAPACITY",
        "state_history_limit": "STATE_HISTORY_LIMIT",
            "stage_hysteresis": "STAGE_HYSTERESIS",
            "roleplay_prompt_mode": "ROLEPLAY_PROMPT_MODE",
            "observability_trace_sample_rate": "OBSERVABILITY_TRACE_SAMPLE_RATE",
            "observability_prompt_capture_mode": "OBSERVABILITY_PROMPT_CAPTURE_MODE",
            "observability_prompt_sample_rate": "OBSERVABILITY_PROMPT_SAMPLE_RATE",
            "observability_prompt_max_chars": "OBSERVABILITY_PROMPT_MAX_CHARS",
            "observability_step_extra_max_chars": "OBSERVABILITY_STEP_EXTRA_MAX_CHARS",
            "observability_prompt_redact": "OBSERVABILITY_PROMPT_REDACT",
            "observability_llm_cost_json": "OBSERVABILITY_LLM_COST_JSON",
            "observability_trace_retention_days": "OBSERVABILITY_TRACE_RETENTION_DAYS",
            "observability_prompt_retention_days": "OBSERVABILITY_PROMPT_RETENTION_DAYS",
            "observability_decision_retention_days": "OBSERVABILITY_DECISION_RETENTION_DAYS",
            "observability_llm_call_retention_days": "OBSERVABILITY_LLM_CALL_RETENTION_DAYS",
            "evaluation_llm_judge_sample_rate": "EVALUATION_LLM_JUDGE_SAMPLE_RATE",
            "rel_repetition_decay": "REL_REPETITION_DECAY",
            "rel_trust_negative_amp": "REL_TRUST_NEGATIVE_AMP",
            "rel_comfort_drift": "REL_COMFORT_DRIFT",
            "rel_comfort_baseline_json": "REL_COMFORT_BASELINE_JSON",
            "rel_milestone_delta_cap": "REL_MILESTONE_DELTA_CAP",
            "rel_signal_evidence_window": "REL_SIGNAL_EVIDENCE_WINDOW",
            "rel_conflict_cold_hours": "REL_CONFLICT_COLD_HOURS",
            "rel_conflict_max_cold_days": "REL_CONFLICT_MAX_COLD_DAYS",
            "rel_conflict_recover_positive": "REL_CONFLICT_RECOVER_POSITIVE",
            "rel_neglect_days_json": "REL_NEGLECT_DAYS_JSON",
            "rel_tension_daily_decay": "REL_TENSION_DAILY_DECAY",
            "evaluation_relationship_enabled": "EVALUATION_RELATIONSHIP_ENABLED",
            "world_time_mode": "WORLD_TIME_MODE",
            "world_sim_rate": "WORLD_SIM_RATE",
            "world_context_char_budget": "WORLD_CONTEXT_CHAR_BUDGET",
            "world_event_grace_hours": "WORLD_EVENT_GRACE_HOURS",
            "action_plan_max_steps": "ACTION_PLAN_MAX_STEPS",
            "action_plan_expires_minutes": "ACTION_PLAN_EXPIRES_MINUTES",
            "action_max_active_per_user": "ACTION_MAX_ACTIVE_PER_USER",
            "action_dedupe_window_hours": "ACTION_DEDUPE_WINDOW_HOURS",
            "action_execution_timeout_seconds": "ACTION_EXECUTION_TIMEOUT_SECONDS",
            "action_retry_max_attempts": "ACTION_RETRY_MAX_ATTEMPTS",
            "action_retry_backoff_seconds": "ACTION_RETRY_BACKOFF_SECONDS",
            "action_maintenance_interval_seconds": "ACTION_MAINTENANCE_INTERVAL_SECONDS",
            "action_context_char_budget": "ACTION_CONTEXT_CHAR_BUDGET",
            "action_memory_policy_json": "ACTION_MEMORY_POLICY_JSON",
            "action_relationship_enabled": "ACTION_RELATIONSHIP_ENABLED",
            "action_record_retention_days": "ACTION_RECORD_RETENTION_DAYS",
            "autonomy_action_enabled": "AUTONOMY_ACTION_ENABLED",
            "autonomy_action_daily_limit": "AUTONOMY_ACTION_DAILY_LIMIT",
            "evaluation_action_enabled": "EVALUATION_ACTION_ENABLED",
            "evaluation_development_enabled": "EVALUATION_DEVELOPMENT_ENABLED",
        }
        for key, env in env_map.items():
            if key in kwargs:
                set_known_env(monkeypatch, env, kwargs[key])
        for key, value in kwargs.items():
            if key not in env_map:
                set_known_env(monkeypatch, key.upper(), value)
        get_settings.cache_clear()

    yield _apply
    get_settings.cache_clear()


SLOW_TEST_FILES = {
    # 慢测试：本地 SSE server 线程 / 轮询等待。
    "test_chat_http_integration.py",
    "test_turn_meta_stream.py",
    "test_foreground_cutover_parity.py",
    "test_six_stage_loop_parity.py",
    "test_goal_e2e.py",
    # TestClient(app) 全应用 E2E / strict 需要真实 PostgreSQL 的迁移类。
    # (旧疑 TestClient+lifespan 挂起，实为世界维护循环连真实 PG；已由 autouse _offline_repos 修复，非版本问题。)
    "test_e2e.py",
    "test_debug_decisions.py",
    "test_debug_evaluation.py",
    "test_debug_proactive_correlation.py",
    "test_debug_state_history.py",
    "test_log_redaction.py",
    "test_memory_e2e.py",
    "test_proactive_api.py",
    "test_state_e2e.py",
    "test_v65_matrix.py",
    "test_v2_all_flags_smoke.py",
    "test_activity_continuity.py",
    "test_autonomy_matrix.py",
    "test_behavior_pipeline.py",
    "test_mode_persistence.py",
    "test_db_migration.py",
}
GOLDEN_TEST_FILES = {"test_prompt_golden.py"}
LEGACY_TEST_DIRS = ("v2", "v8.5", "v22", "v23", "v24", "v25", "v26")
"""历史版本套件（2026-10-08 归档）：被测模块仍在跑，但默认不收集，`--run-legacy` 时才参与全量回归。"""


def _mark_app_based(item) -> None:
    """按「用例所在模块是否加载 FastAPI 应用」打 `_APP_BASED_MARKER`。

    判据（任一命中即标记）：
      1) 模块对象已有 `app` 属性，且其类型属 FastAPI（`from app.main import app` 的形态）；
      2) 模块源码含 `app.main` 导入（覆盖 `import app.main` 等写法）。
    命中后由 autouse `_default_auth_user` 安装 require_user override。
    """
    module = getattr(item, "module", None)
    if module is None:
        return

    app_obj = getattr(module, "app", None)
    if app_obj is not None and app_obj.__class__.__name__ == "FastAPI":
        item.add_marker(_APP_BASED_MARKER)
        return

    source = getattr(module, "__source__", None)
    if source is None:
        try:
            source = Path(module.__file__).read_text(encoding="utf-8", errors="ignore")
        except (OSError, TypeError):
            source = ""
    if "app.main" in source or "from app import main" in source:
        item.add_marker(_APP_BASED_MARKER)


def pytest_addoption(parser):
    parser.addoption(
        "--run-legacy",
        action="store_true",
        default=False,
        help="收集并运行历史版本套件（tests/v2、v8.5、v22~v26）",
    )


def pytest_ignore_collect(collection_path, config):
    if config.getoption("--run-legacy"):
        return False
    tests_root = Path(__file__).resolve().parent
    try:
        relative = collection_path.resolve().relative_to(tests_root)
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0] in LEGACY_TEST_DIRS


def pytest_collection_modifyitems(config, items):
    for item in items:
        path = item.path.as_posix().replace("\\", "/")
        filename = item.path.name
        fixtures = set(item.fixturenames or ())
        _mark_app_based(item)
        if filename in GOLDEN_TEST_FILES:
            item.add_marker(pytest.mark.golden)
            item.add_marker(pytest.mark.unit)
            continue
        if "db_session_factory" in fixtures:
            item.add_marker(pytest.mark.integration)
        if "asgi_transport" in fixtures or "ASGITransport" in path or "/tests/e2e/" in path:
            item.add_marker(pytest.mark.api)
            if "/tests/e2e/" in path:
                item.add_marker(pytest.mark.e2e)
        own_markers = {
            m.name
            for m in item.iter_markers()
            if m.name in {"unit", "api", "integration", "e2e", "golden"}
        }
        if not own_markers:
            if "/tests/unit/" in path:
                item.add_marker(pytest.mark.unit)
            elif "/tests/integration/" in path:
                item.add_marker(pytest.mark.integration)
            else:
                item.add_marker(pytest.mark.integration)
        if any(f"/tests/{legacy_dir}/" in path for legacy_dir in LEGACY_TEST_DIRS):
            item.add_marker(pytest.mark.legacy)
        if filename in SLOW_TEST_FILES:
            item.add_marker(pytest.mark.slow)
