from app.services import agent_service


def _role_mode(confidence=0.9, mode="default"):
    return {
        "RoleMode": {
            "mode": mode,
            "intent": "casual",
            "confidence": confidence,
            "reason": "hi",
        }
    }


def _turn_analysis(event="setback", behavior="comfort", emotion="sad"):
    return {
        "TurnAnalysis": {
            "user_emotion": {"emotion": emotion, "event": event},
            "behavior": {"behavior": behavior, "reason": "测试"},
        }
    }


def _memory_decision():
    return {
        "MemoryDecision": {
            "should_save": False,
            "memory": None,
            "memory_type": "preference",
            "importance": 0.0,
        }
    }


async def _collect(session_id, content, llm):
    chunks = []
    async for token in agent_service.stream_chat(
        session_id, "default-user", content, llm=llm
    ):
        chunks.append(token)
    return "".join(chunks)


async def test_stream_chat_injects_state_and_behavior_sections(
    db_session_factory, fake_llm
):
    llm = fake_llm(
        response=["嗯"],
        structured_responses={
            **_role_mode(),
            **_turn_analysis(event="setback", behavior="comfort"),
            **_memory_decision(),
        },
    )
    reply = await _collect("s-v2-1", "我今天压力很大", llm)
    assert reply == "嗯"

    rendered = str(llm.seen_messages)
    assert "【角色当前状态】" in rendered
    assert "【与用户的关系】" in rendered
    assert "【本轮行为指令】" in rendered
    assert "不要急着给建议" in rendered


async def test_stream_chat_degrades_analysis_failure(db_session_factory, fake_llm):
    llm = fake_llm(
        response=["嗯"],
        structured_responses={**_role_mode(), **_memory_decision()},
        structured_errors={"TurnAnalysis": RuntimeError("analysis boom")},
    )
    reply = await _collect("s-v2-2", "我今天压力很大", llm)
    assert reply == "嗯"

    rendered = str(llm.seen_messages)
    assert "【角色当前状态】" in rendered
    assert "以平常心自然回应" in rendered


async def test_stream_chat_degrades_analysis_none_output(db_session_factory, fake_llm):
    llm = fake_llm(
        response=["嗯"],
        structured_responses={**_role_mode(), **_memory_decision()},
    )
    reply = await _collect("s-v2-3", "随便聊聊", llm)
    assert reply == "嗯"
    assert "【角色当前状态】" in str(llm.seen_messages)


async def test_stream_chat_degrades_router_failure(db_session_factory, fake_llm):
    llm = fake_llm(
        response=["嗯"],
        structured_responses={**_turn_analysis(), **_memory_decision()},
        structured_errors={"RoleMode": RuntimeError("router boom")},
    )
    reply = await _collect("s-v2-4", "Python 报错", llm)
    assert reply == "嗯"
    rendered = str(llm.seen_messages)
    assert "日常模式" in rendered
    assert "专业模式" not in rendered
