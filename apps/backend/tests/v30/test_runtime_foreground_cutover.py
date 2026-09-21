"""RT-015 前置切片：前台流式契约冻结 + 入口收敛登记守卫。

本文件只覆盖**收编前即可验证、收编后必须继续成立**的部分：
`turn_meta` 键集与顺序、`done` 字段、每轮 1 行 `loop_runs`、开关关闭时的等价性、
`agent_service.stream_chat` 调用点登记完整性。

收编本体（`chat_pipeline` 改由 `AgentLoop` 驱动 / 段序列只来自 `profiles.py` /
收尾委派循环）尚未落地，因此 RT-015 §7.1 的 `test_single_loop_path` 与
`test_cleanup_delegated_to_loop` **不在本文件覆盖范围内**；缺口与前置条件登记在
`docs/version/v3.0.0/entry-convergence.md` §5。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.application.agent_runtime.models import RUN_KIND_FOREGROUND_CHAT
from app.core.settings import get_settings
from app.repositories import loop_run_repository
from app.services import agent_service

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent.parent
ENTRY_DOC = REPO / "docs" / "version" / "v3.0.0" / "entry-convergence.md"

USER_ID = "default-user"

TURN_META_ORDER: tuple[str, ...] = (
    "kind",
    "role_mode",
    "analysis",
    "scene_intent",
    "scene_state",
    "intention",
    "current_goal",
    "behavior",
    "mode",
)
DONE_KEYS = frozenset({"kind", "session_id", "turn_id", "request_id"})
CALL_PATTERN = re.compile(r"agent_service\.stream_chat\s*\(")


def _llm(fake_llm):
    return fake_llm(
        response=["嗯"],
        structured_responses={
            "RoleMode": {
                "mode": "default",
                "intent": "casual",
                "confidence": 0.9,
                "reason": "hi",
            },
            "TurnAnalysis": {
                "user_emotion": {"emotion": "sad", "event": "setback"},
                "behavior": {"behavior": "comfort", "reason": "测试"},
            },
        },
    )


async def _events(session_id: str, content: str, llm) -> list[dict]:
    events: list[dict] = []
    async for event in agent_service.stream_chat(session_id, USER_ID, content, llm=llm):
        events.append(event)
    return events


def _core_keys(meta: dict) -> list[str]:
    return [name for name in meta if name != "action_intent"]


class TestStreamingContract:
    """收编前基线 = 收编后必须逐字段一致（RT-015 AC1 / AC4 / AC7）。"""

    pytestmark = pytest.mark.integration

    async def test_turn_meta_keys_and_order_unchanged(
        self, db_session_factory, fake_llm
    ):
        events = await _events("s-v30-meta", "我今天压力很大", _llm(fake_llm))

        meta = events[0]
        assert meta["kind"] == "turn_meta"
        assert _core_keys(meta) == list(TURN_META_ORDER)
        keys = list(meta)
        if "action_intent" in keys:
            assert keys[-1] == "action_intent"

    async def test_done_event_unchanged(self, db_session_factory, fake_llm):
        events = await _events("s-v30-done", "在吗", _llm(fake_llm))

        done = events[-1]
        assert done["kind"] == "done"
        assert set(done) == DONE_KEYS
        assert done["session_id"] == "s-v30-done"
        assert str(done["turn_id"]).isdigit()
        assert done["request_id"]
        assert all(event["kind"] == "token" for event in events[1:-1])

    async def test_run_metadata_written(self, db_session_factory, fake_llm):
        before = len(loop_run_repository.list_recent(USER_ID, limit=200))

        await _events("s-v30-runs", "在吗", _llm(fake_llm))

        runs = loop_run_repository.list_recent(USER_ID, limit=200)
        assert len(runs) == before + 1
        assert runs[0].run_kind == RUN_KIND_FOREGROUND_CHAT
        assert runs[0].status in {"done", "degraded"}

    async def test_flags_off_means_legacy_context_assembly(
        self, db_session_factory, fake_llm
    ):
        settings = get_settings()
        assert settings.runtime_context_freeze_enabled is False
        assert settings.runtime_state_versioning_enabled is False

        events = await _events("s-v30-flags", "在吗", _llm(fake_llm))

        assert _core_keys(events[0]) == list(TURN_META_ORDER)
        assert events[-1]["kind"] == "done"


class TestEntryConvergence:
    """RT-015 AC6：生产调用点必须登记在案，不得静默保留双入口。"""

    pytestmark = pytest.mark.unit

    def test_agent_service_call_sites_registered(self):
        doc = ENTRY_DOC.read_text(encoding="utf-8")
        found: list[str] = []
        unregistered: list[str] = []
        for path in sorted((BACKEND / "app").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if not CALL_PATTERN.search(line):
                    continue
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"'):
                    continue
                rel = path.relative_to(BACKEND).as_posix()
                found.append(f"{rel}:{lineno}")
                if rel not in doc:
                    unregistered.append(f"{rel}:{lineno}")

        assert found, "未找到 agent_service.stream_chat 调用点，登记守卫本身失效"
        assert unregistered == [], f"未登记的生产调用点：{unregistered}"

    def test_entry_convergence_doc_is_present(self):
        doc = ENTRY_DOC.read_text(encoding="utf-8")

        assert "stream_chat" in doc
        assert "保留" in doc
