"""主动消息出站端口（AUTO-005）：执行层与 Channel 实现的唯一接缝。

边界守门（test_feishu_boundary R2）禁止 services/application 直接 import
`app.channels.<impl>`；具体 sender 由组合根（main.py lifespan）按渠道
启用状态注入（依赖倒置）。未注册 outbound（纯 Web 部署 / 单测）时，
执行层保持内部落库语义：delivered 即内部投递完成，
external_message_id 留空——不伪造外部投递结果。
"""

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from app.channels.base import SendResult

logger = logging.getLogger(__name__)

ProactiveSender = Callable[[str, str, str], Awaitable[SendResult]]


@dataclass(frozen=True)
class ProactiveOutbound:
    channel: str
    send: ProactiveSender


_outbound: ProactiveOutbound | None = None


def register_proactive_outbound(outbound: ProactiveOutbound) -> None:
    global _outbound
    _outbound = outbound


def reset_proactive_outbound() -> None:
    global _outbound
    _outbound = None


def get_proactive_outbound() -> ProactiveOutbound | None:
    return _outbound
