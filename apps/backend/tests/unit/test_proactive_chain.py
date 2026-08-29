"""V7-005：Proactive Chain（FakeLLM 生成 / 空文本失败 / 模板符校验）。"""

from app.chains import proactive_chain
from app.services.trace_collector import TurnTraceSession


def test_generate_returns_text_via_fakellm(fake_llm):
    llm = fake_llm(response=["忙完了吗？记得喝口水。"])
    import asyncio

    text = asyncio.run(proactive_chain.generate("陪伴用户放松", "check_in", llm=llm))
    assert text == "忙完了吗？记得喝口水。"


def test_generate_prompt_carries_goal_intention_and_rules(fake_llm):
    llm = fake_llm(response=["嗯"])
    import asyncio

    asyncio.run(
        proactive_chain.generate(
            "陪伴用户放松", "check_in", "用户：我去忙了", llm=llm
        )
    )
    joined = " ".join(str(m) for m in llm.seen_messages)
    assert "陪伴用户放松" in joined
    assert "check_in" in joined
    assert "我去忙了" in joined
    assert "不追问施压" in joined


def test_generate_empty_text_fails(fake_llm):
    llm = fake_llm(response=["   "])
    import asyncio

    trace = TurnTraceSession()
    text = asyncio.run(
        proactive_chain.generate("陪伴用户放松", "check_in", llm=llm, trace=trace)
    )
    assert text is None
    assert trace.steps[-1].status == "error"


def test_generate_template_marker_fails(fake_llm):
    llm = fake_llm(response=["{goal_description} 好了吗"])
    import asyncio

    text = asyncio.run(proactive_chain.generate("陪伴用户放松", "check_in", llm=llm))
    assert text is None


def test_generate_llm_exception_returns_none():
    class _Boom:
        def bind(self, **kwargs):
            return self

        async def ainvoke(self, value):
            raise RuntimeError("llm down")

    import asyncio

    text = asyncio.run(proactive_chain.generate("目标", "check_in", llm=_Boom()))
    assert text is None
