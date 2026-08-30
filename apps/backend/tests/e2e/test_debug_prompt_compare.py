"""V7.8 debug prompt 比较端点。"""

from datetime import datetime

from httpx import ASGITransport, AsyncClient
import pytest

from app.main import app
from app.repositories import prompt_snapshot_repository
from app.models.observability import CallSite, PromptSnapshot


def _save(snapshot_id, content_len):
    prompt_snapshot_repository.save(
        PromptSnapshot(
            id=snapshot_id,
            request_id="req-cmp",
            call_site=CallSite.ANSWER,
            model="fake",
            messages=[{"role": "system", "content": "x" * content_len}],
            section_budget={"total": content_len, "budget": 12000},
            created_at=datetime.now(),
        )
    )


@pytest.mark.asyncio
async def test_debug_prompt_compare_endpoint(db_session_factory):
    _save("cmp-a", 100)
    _save("cmp-b", 400)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/debug/prompts/compare", params={"a": "cmp-a", "b": "cmp-b"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_chars"] == {"a": 100, "b": 400}
        assert body["section_diff"]["total"] == {"a": 100, "b": 400}

        missing = await client.get(
            "/api/v1/debug/prompts/compare", params={"a": "cmp-a", "b": "no-such"}
        )
        assert missing.status_code == 404
