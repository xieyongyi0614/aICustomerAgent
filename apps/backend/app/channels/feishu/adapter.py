"""飞书入站编排骨架：处理入口 + trace 起点 + 全异常兜底（FEISHU-002）。

身份映射（FEISHU-003）/ 管线调用（FEISHU-004）/ 出站发送（FEISHU-005）
后续在同一函数体内顺序接线，不新增调度层。
"""

import logging
import time

from app.channels.base import InboundMessage
from app.services import trace_collector

logger = logging.getLogger(__name__)


async def handle_inbound_message(inbound: InboundMessage) -> None:
    started = time.perf_counter()
    try:
        trace = trace_collector.begin_trace()
        logger.info(
            "feishu inbound received: channel=%s external_user_id=%s reply_ref=%s text_len=%d",
            inbound.channel,
            inbound.external_user_id,
            inbound.reply_ref,
            len(inbound.text),
        )
        trace.record(
            "feishu_dispatch",
            (time.perf_counter() - started) * 1000,
            status="not_implemented",
        )
    except Exception:
        logger.exception("feishu inbound handling failed")


def reset_feishu_adapter() -> None:
    trace_collector.reset_trace_collector()
