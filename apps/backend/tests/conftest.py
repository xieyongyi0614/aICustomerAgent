import os
import re
import time
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
os.environ.setdefault("AUTONOMY_ENABLED", "false")
os.environ.setdefault("EVALUATION_ENABLED", "false")
os.environ.setdefault("OBSERVABILITY_PERSIST_ENABLED", "false")
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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.deps import get_chat_llm
from app.core import llm_factory
from app.services import agent_service
from app.services import relationship_evaluation as relationship_evaluation_service
from app.services import relationship_narrative as relationship_narrative_service
from app.services import relationship_patterns as relationship_patterns_service
from app.services.memory2 import attribution as memory2_attribution
from app.services.memory2 import commands as memory2_commands
from app.services.memory2 import evaluator as memory2_evaluator
from app.services.memory2 import ingest as memory2_ingest
from app.services.memory2 import job_worker as memory2_job_worker
from app.services.memory2 import lifecycle as memory2_lifecycle
from app.services.memory2 import migration as memory2_migration
from app.services.memory2 import retriever as memory2_retriever
from app.services import evolution as evolution_service
from app.services.development import aggregate as development_aggregate
from app.services.development import audit as development_audit
from app.services.development import attribution as development_attribution
from app.services.development import evaluation as development_evaluation
from app.services.development import policy as development_policy
from app.services.reflection import attribution as reflection_attribution
from app.services.reflection import evidence as reflection_evidence
from app.services.reflection import evaluation as reflection_evaluation
from app.services.reflection import lifecycle as reflection_lifecycle
from app.services.reflection import reflector as reflection_reflector
from app.services.reflection import tool_feed as reflection_tool_feed
from app.services.reflection import triggers as reflection_triggers
from app.core.db import Base
from app.core.settings import get_settings
from app.main import app
from app.repositories import (
    action_repository,
    agent_metric_repository,
    agent_state_snapshot_repository,
    background_job_repository,
    character_state_repository,
    channel_identity_repository,
    conversation_repository,
    decision_repository,
    emotion_history_repository,
    evaluation_repository,
    goal_repository,
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
    world_repository,
    world_simulation_repository,
)

WAIT_TIMEOUT = float(os.environ.get("E2E_WAIT_TIMEOUT", "3.0"))

_REPO_MODULES = (
    action_repository,
    background_job_repository,
    channel_identity_repository,
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
    world_repository,
    world_simulation_repository,
    relationship_milestone_repository,
    relationship_conflict_repository,
    relationship_snapshot_repository,
)

_SERVICE_DB_MODULES = (
    memory2_attribution,
    memory2_commands,
    memory2_evaluator,
    memory2_ingest,
    memory2_job_worker,
    memory2_lifecycle,
    memory2_migration,
    relationship_evaluation_service,
    relationship_narrative_service,
    relationship_patterns_service,
    memory2_retriever,
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
        app.dependency_overrides[get_chat_llm] = lambda: llm
        return llm

    yield _apply
    app.dependency_overrides.pop(get_chat_llm, None)


@pytest.fixture(autouse=True)
def _offline_repos(monkeypatch):
    """Autouse：除显式 TEST_USE_POSTGRES=1 外，把所有 repo 与 memory2 服务的 SessionLocal 指向内存 SQLite。

    修复根因B：PromptBuilder.build(analysis=...) 等“纯单测”隐含访问
    relationship_milestone_repository.SessionLocal，若不替换则连真实 PostgreSQL(.env) 而挂起。
    services 层新增模块级 SessionLocal 的模块必须同步加入 _SERVICE_DB_MODULES。
    """
    if os.environ.get("TEST_USE_POSTGRES") == "1":
        yield None
        return
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    for module in (*_REPO_MODULES, *_SERVICE_DB_MODULES):
        monkeypatch.setattr(module, "SessionLocal", testing_session)
    yield testing_session
    deadline = time.time() + 2.0
    while (
        (agent_service._background_tasks or chat_post_process_tasks() or observability_tasks())
        and time.time() < deadline
    ):
        time.sleep(0.02)

    from app.application import post_process as chat_post_process

    chat_post_process.reset_user_write_locks()
    Base.metadata.drop_all(engine)
    engine.dispose()


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
    """写入环境变量；仅对版本号开关（`V2_*` / `V21_*` / …）校验字段存在。

    `v24_tool_env` 除 `V24_*` 开关外还用于注入外部工具密钥（如
    `EXT_API_WEATHER_TOKEN`）这类非 settings 字段的环境变量，故只守卫会被改名
    影响的版本号开关，其余原样放行。
    """
    if _VERSIONED_ENV_KEY.match(env_key.upper()):
        set_known_env(monkeypatch, env_key, value)
    else:
        monkeypatch.setenv(env_key, str(value))


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
            "observability_persist_enabled": "OBSERVABILITY_PERSIST_ENABLED",
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
            "evaluation_enabled": "EVALUATION_ENABLED",
            "evaluation_llm_judge_sample_rate": "EVALUATION_LLM_JUDGE_SAMPLE_RATE",
            "rel_evolution_enabled": "REL_EVOLUTION_ENABLED",
            "rel_repetition_decay": "REL_REPETITION_DECAY",
            "rel_trust_negative_amp": "REL_TRUST_NEGATIVE_AMP",
            "rel_comfort_drift": "REL_COMFORT_DRIFT",
            "rel_comfort_baseline_json": "REL_COMFORT_BASELINE_JSON",
            "rel_milestone_delta_cap": "REL_MILESTONE_DELTA_CAP",
            "rel_signal_llm_enabled": "REL_SIGNAL_LLM_ENABLED",
            "rel_signal_evidence_window": "REL_SIGNAL_EVIDENCE_WINDOW",
            "rel_milestone_enabled": "REL_MILESTONE_ENABLED",
            "rel_conflict_enabled": "REL_CONFLICT_ENABLED",
            "rel_conflict_cold_hours": "REL_CONFLICT_COLD_HOURS",
            "rel_conflict_max_cold_days": "REL_CONFLICT_MAX_COLD_DAYS",
            "rel_conflict_recover_positive": "REL_CONFLICT_RECOVER_POSITIVE",
            "rel_neglect_days_json": "REL_NEGLECT_DAYS_JSON",
            "rel_tension_daily_decay": "REL_TENSION_DAILY_DECAY",
            "evaluation_relationship_enabled": "EVALUATION_RELATIONSHIP_ENABLED",
            "world_enabled": "WORLD_ENABLED",
            "world_time_mode": "WORLD_TIME_MODE",
            "world_sim_rate": "WORLD_SIM_RATE",
            "world_context_char_budget": "WORLD_CONTEXT_CHAR_BUDGET",
            "world_household_autoseed_enabled": "WORLD_HOUSEHOLD_AUTOSEED_ENABLED",
            "world_interpreter_enabled": "WORLD_INTERPRETER_ENABLED",
            "world_llm_assist_enabled": "WORLD_LLM_ASSIST_ENABLED",
            "world_memory_bridge_enabled": "WORLD_MEMORY_BRIDGE_ENABLED",
            "world_event_grace_hours": "WORLD_EVENT_GRACE_HOURS",
            "action_enabled": "ACTION_ENABLED",
            "action_detector_enabled": "ACTION_DETECTOR_ENABLED",
            "action_plan_max_steps": "ACTION_PLAN_MAX_STEPS",
            "action_plan_expires_minutes": "ACTION_PLAN_EXPIRES_MINUTES",
            "action_max_active_per_user": "ACTION_MAX_ACTIVE_PER_USER",
            "action_dedupe_window_hours": "ACTION_DEDUPE_WINDOW_HOURS",
            "action_execution_timeout_seconds": "ACTION_EXECUTION_TIMEOUT_SECONDS",
            "action_retry_max_attempts": "ACTION_RETRY_MAX_ATTEMPTS",
            "action_retry_backoff_seconds": "ACTION_RETRY_BACKOFF_SECONDS",
            "action_maintenance_interval_seconds": "ACTION_MAINTENANCE_INTERVAL_SECONDS",
            "action_context_char_budget": "ACTION_CONTEXT_CHAR_BUDGET",
            "action_memory_policy_enabled": "ACTION_MEMORY_POLICY_ENABLED",
            "action_memory_policy_json": "ACTION_MEMORY_POLICY_JSON",
            "action_relationship_enabled": "ACTION_RELATIONSHIP_ENABLED",
            "action_record_retention_days": "ACTION_RECORD_RETENTION_DAYS",
            "autonomy_action_enabled": "AUTONOMY_ACTION_ENABLED",
            "autonomy_action_daily_limit": "AUTONOMY_ACTION_DAILY_LIMIT",
            "evaluation_action_enabled": "EVALUATION_ACTION_ENABLED",
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


def pytest_collection_modifyitems(config, items):
    for item in items:
        path = item.path.as_posix().replace("\\", "/")
        filename = item.path.name
        fixtures = set(item.fixturenames or ())
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
        if filename in SLOW_TEST_FILES:
            item.add_marker(pytest.mark.slow)
