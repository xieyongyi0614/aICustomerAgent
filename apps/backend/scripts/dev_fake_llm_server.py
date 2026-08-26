import os
import sys

os.environ.setdefault("OPENAI_API_KEY", "test")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn

from app.api.v1.deps import get_chat_llm
from app.main import app
from tests.conftest import FakeLLM

llm = FakeLLM(
    response=["好的", "，我先记下了。"],
    structured_responses={
        "RoleMode": {
            "mode": "immersive",
            "intent": "emotional",
            "confidence": 0.2,
            "reason": "fake 低置信示例",
        },
        "TurnAnalysis": {
            "user_emotion": {"emotion": "sad", "event": "setback"},
            "behavior": {"behavior": "comfort", "reason": "先接住情绪"},
        },
        "StateUpdateDecision": {
            "mood": "worried",
            "mood_reason": "用户压力较大",
            "inner_state": "担心用户熬夜赶工",
            "current_topic": "用户的调试控制台项目",
        },
        "MemoryDecision": {
            "should_save": True,
            "memory": "用户正在开发 Character Agent Debug Console",
            "memory_type": "goal",
            "importance": 0.85,
        },
    },
)

app.dependency_overrides[get_chat_llm] = lambda: llm

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
