import logging

import pytest

from app.core.logutils import content_preview
from app.core.settings import get_settings


class TestContentPreview:
    def test_default_zero_hides_content(self):
        get_settings().log_content_preview_chars = 0
        assert content_preview("用户说了很长的一段话") == "<10 字符>"

    def test_positive_limit_truncates(self):
        get_settings().log_content_preview_chars = 4
        assert content_preview("一句话内容很长") == "一句话内容…"
        assert content_preview("短") == "短"

    def test_empty_text(self):
        assert content_preview("") == ""
        assert content_preview(None) == ""


class TestLogRedaction:
    def test_reply_not_logged_in_full_at_info_level(self, db_session_factory, caplog):
        from app.core import llm_factory
        from app.main import app
        from fastapi.testclient import TestClient

        from tests.conftest import FakeLLM

        llm = FakeLLM(
            response=["这句", "话包含用户隐私内容xyz"],
            structured_responses={
                "RoleMode": {"mode": "default", "intent": "casual", "confidence": 0.9, "reason": "hi"},
                "MemoryExtraction": {"candidates": []},
            },
        )
        llm_factory.set_llm(llm)
        try:
            with caplog.at_level(logging.INFO):
                with TestClient(app) as client:
                    resp = client.post("/api/v1/chat/message", json={"content": "在吗"})
                    assert resp.status_code == 200
        finally:
            llm_factory.reset_llm()
        info_text = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.INFO)
        assert "这句话包含用户隐私内容xyz" not in info_text
        assert "模型输出完成" in info_text
