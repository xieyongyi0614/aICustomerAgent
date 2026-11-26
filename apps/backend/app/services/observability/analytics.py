"""PLT-003 埋点与崩溃上报：日志禁打账目金额与健康数值。"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("zhaoxi.analytics")

_AMOUNT = re.compile(r"(¥|yuan|amount|金额)\s*[=:：]?\s*\d+", re.I)
_HEALTH = re.compile(r"(hr|heart|spo2|sleep|steps|心率|步数|睡眠)\s*[=:：]?\s*\d+", re.I)


def redact_metric_text(text: str) -> str:
    text = _AMOUNT.sub("[redacted-money]", text)
    text = _HEALTH.sub("[redacted-health]", text)
    return text


def track_event(name: str, **props) -> None:
    safe = {k: redact_metric_text(str(v)) for k, v in props.items()}
    logger.info("event %s %s", name, safe)
