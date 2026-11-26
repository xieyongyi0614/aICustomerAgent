"""飞书身份适配：InboundMessage → ChannelIdentity（纯组装，零 IO，FEISHU-003）。

派生规则（open_id → internal_user_id）不在本模块——它属通道无关逻辑，见
channel_identity_service。本模块只把通道私有值装进通道无关契约。
"""

from app.channels.base import ChannelIdentity, InboundMessage

FEISHU_CHANNEL = "feishu"


def to_channel_identity(inbound: InboundMessage) -> ChannelIdentity:
    tenant = inbound.metadata.get("tenant_key") if inbound.metadata else None
    return ChannelIdentity(
        channel=FEISHU_CHANNEL,
        external_user_id=inbound.external_user_id,
        tenant=tenant if isinstance(tenant, str) and tenant else None,
        display_name=None,
    )
