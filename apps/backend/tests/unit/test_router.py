import pytest

from app.core import llm_factory
from app.chains import router_chain
from app.models.router import RoleMode


@pytest.mark.asyncio
async def test_route_parses_structured_output(fake_llm):
    llm_factory.set_llm(fake_llm(structured_responses={
        "RoleMode": {
            "mode": "professional",
            "intent": "technical",
            "confidence": 0.9,
            "reason": "tech",
        },
    }))
    result = await router_chain.route("Python 报错怎么排查")
    assert isinstance(result, RoleMode)
    assert result.mode == "professional"
    assert result.intent == "technical"


@pytest.mark.asyncio
async def test_route_template_rendered(fake_llm):
    llm = fake_llm(structured_responses={
        "RoleMode": {"mode": "default", "intent": "casual", "confidence": 0.8, "reason": "hi"},
    })
    llm_factory.set_llm(llm)
    await router_chain.route("你好")
    inputs = llm.seen_messages[0][0]
    rendered = inputs.to_messages()[0].content
    assert "你好" in rendered
    assert "{user_message}" not in rendered
