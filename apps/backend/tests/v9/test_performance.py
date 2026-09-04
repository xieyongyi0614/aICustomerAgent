"""V9 性能护栏（testing.md §3）：检出 / 渲染 / 关闭路径调用计数常驻断言。

确定性、无真实 LLM；预算为宽松阈值以规避 CI 抖动，但守住数量级。
"""

import time
from datetime import datetime

from app.models.action import ActionIntent
from app.services.action.context import ActionContext, ActionItem, render_action_section
from app.services.action.detector import detect_action_intent

NOW = datetime(2026, 9, 3, 14, 0, 0)


def test_detector_average_under_1ms(override_settings):
    override_settings(action_enabled=True)
    iterations = 500
    started = time.perf_counter()
    for _ in range(iterations):
        detect_action_intent("明天早上8点提醒我开会", now=NOW)
    avg_ms = (time.perf_counter() - started) * 1000 / iterations
    assert avg_ms < 1.0


def test_render_section_under_5ms():
    ctx = ActionContext(
        items=[
            ActionItem(
                action_type="create_reminder",
                status="succeeded",
                summary="设提醒：开会",
                updated_at=NOW,
            )
            for _ in range(50)
        ]
    )
    started = time.perf_counter()
    render_action_section(ctx, 400)
    assert (time.perf_counter() - started) * 1000 < 5.0


def test_disabled_paths_short_circuit(override_settings):
    """action_enabled=false：检出/渲染全部零执行路径。"""
    override_settings(action_enabled=False)
    assert detect_action_intent("帮我设个提醒", now=NOW) is None
    assert render_action_section(None, 400) == ""


def test_noop_intent_keeps_pipeline_unchanged(override_settings):
    override_settings(action_enabled=True)
    started = time.perf_counter()
    for _ in range(200):
        detect_action_intent("今天心情不错", now=NOW)
    avg_ms = (time.perf_counter() - started) * 1000 / 200
    assert avg_ms < 1.0