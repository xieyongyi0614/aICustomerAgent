import os
import time
from typing import Any

os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("AUTONOMY_ENABLED", "false")
os.environ.setdefault("EVALUATION_ENABLED", "false")
os.environ.setdefault("OBSERVABILITY_PERSIST_ENABLED", "false")
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
from app.core.db import Base
from app.core.settings import get_settings
from app.main import app
from app.repositories import (
    character_state_repository,
    conversation_repository,
    decision_repository,
    emotion_history_repository,
    evaluation_repository,
    goal_repository,
    llm_call_repository,
    memory_repository,
    proactive_repository,
    prompt_snapshot_repository,
    relationship_event_repository,
    relationship_repository,
    scene_state_repository,
    summary_repository,
    trace_repository,
)

WAIT_TIMEOUT = float(os.environ.get("E2E_WAIT_TIMEOUT", "3.0"))


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


@pytest.fixture
def db_session_factory(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(conversation_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(summary_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(memory_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(character_state_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(relationship_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(relationship_event_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(emotion_history_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(scene_state_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(goal_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(proactive_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(evaluation_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(trace_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(llm_call_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(prompt_snapshot_repository, "SessionLocal", testing_session)
    monkeypatch.setattr(decision_repository, "SessionLocal", testing_session)
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
        }
        for key, env in env_map.items():
            if key in kwargs:
                monkeypatch.setenv(env, str(kwargs[key]))
        get_settings.cache_clear()

    yield _apply
    get_settings.cache_clear()
