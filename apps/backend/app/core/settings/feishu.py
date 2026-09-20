"""飞书渠道设置：开关、凭据、HTTP 策略（FEISHU-001）。"""

import logging

from pydantic import model_validator

from app.core.settings._shared import (
    DOMAIN_MODEL_CONFIG,
    BaseSettings,
    SettingsError,
)

logger = logging.getLogger(__name__)

_POSITIVE_INT_FIELDS = (
    "feishu_max_reply_chars",
    "feishu_dedupe_ttl_seconds",
    "feishu_signature_window_seconds",
    "feishu_max_concurrent_turns",
    "feishu_session_queue_limit",
    "feishu_max_body_bytes",
    "feishu_merge_max_messages",
    "feishu_merge_max_chars",
)

_REQUIRED_CREDENTIALS = (
    ("FEISHU_APP_ID", "feishu_app_id"),
    ("FEISHU_APP_SECRET", "feishu_app_secret"),
    ("FEISHU_VERIFICATION_TOKEN", "feishu_verification_token"),
)


class FeishuSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    feishu_enabled: bool = False
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""
    feishu_dedupe_persistent_enabled: bool = False
    feishu_instance_index: int = 0
    feishu_ingress_sharded_routing_enabled: bool = False
    feishu_router_enabled: bool = False
    feishu_router_instance_urls: str = ""
    feishu_router_timeout_seconds: float = 5.0
    feishu_api_base: str = "https://open.feishu.cn"
    feishu_llm_profile: str = ""
    feishu_timeout_seconds: float = 10.0
    feishu_token_refresh_ratio: float = 0.8
    feishu_max_reply_chars: int = 4000
    feishu_dedupe_ttl_seconds: int = 600
    feishu_signature_window_seconds: int = 300
    feishu_max_concurrent_turns: int = 4
    feishu_session_queue_limit: int = 5
    feishu_max_body_bytes: int = 262144
    feishu_merge_window_ms: int = 800
    feishu_merge_max_messages: int = 10
    feishu_merge_max_chars: int = 20000
    feishu_rate_limit_per_minute: int = 0
    feishu_outbound_idempotency_ttl_seconds: int = 0
    feishu_instance_count: int = 1
    feishu_http_max_attempts: int = 3
    feishu_http_backoff_seconds: float = 0.5
    feishu_http_backoff_max_seconds: float = 8.0

    @model_validator(mode="after")
    def validate_feishu_config(self):
        if not 0.0 < self.feishu_token_refresh_ratio < 1.0:
            raise SettingsError("FEISHU_TOKEN_REFRESH_RATIO 必须在 (0, 1) 开区间内")
        if self.feishu_timeout_seconds <= 0:
            raise SettingsError("FEISHU_TIMEOUT_SECONDS 必须大于 0")
        for field_name in _POSITIVE_INT_FIELDS:
            if getattr(self, field_name) <= 0:
                raise SettingsError(f"{field_name.upper()} 必须大于 0")
        if self.feishu_merge_window_ms < 0:
            raise SettingsError("FEISHU_MERGE_WINDOW_MS 必须 >= 0（0 表示关闭连发合并）")
        if self.feishu_rate_limit_per_minute < 0:
            raise SettingsError(
                "FEISHU_RATE_LIMIT_PER_MINUTE 必须 >= 0（0 表示沿用 CHAT_RATE_LIMIT_PER_MINUTE）"
            )
        if self.feishu_outbound_idempotency_ttl_seconds < 0:
            raise SettingsError(
                "FEISHU_OUTBOUND_IDEMPOTENCY_TTL_SECONDS 必须 >= 0"
                "（0 表示沿用 FEISHU_DEDUPE_TTL_SECONDS）"
            )
        if self.feishu_instance_count < 1:
            raise SettingsError("FEISHU_INSTANCE_COUNT 必须 >= 1（单实例填 1）")
        if not 0 <= self.feishu_instance_index < self.feishu_instance_count:
            raise SettingsError(
                "FEISHU_INSTANCE_INDEX 必须在 [0, FEISHU_INSTANCE_COUNT) 内"
                f"（当前 index={self.feishu_instance_index}, "
                f"count={self.feishu_instance_count}）"
            )
        if self.feishu_http_max_attempts < 1:
            raise SettingsError("FEISHU_HTTP_MAX_ATTEMPTS 必须 >= 1")
        if self.feishu_http_backoff_seconds < 0:
            raise SettingsError("FEISHU_HTTP_BACKOFF_SECONDS 必须 >= 0")
        if self.feishu_http_backoff_max_seconds < self.feishu_http_backoff_seconds:
            raise SettingsError(
                "FEISHU_HTTP_BACKOFF_MAX_SECONDS 必须 >= FEISHU_HTTP_BACKOFF_SECONDS"
            )
        api_base = self.feishu_api_base.rstrip("/")
        if not api_base.startswith(("http://", "https://")):
            raise SettingsError("FEISHU_API_BASE 必须以 http:// 或 https:// 开头")
        self.feishu_api_base = api_base
        if self.feishu_enabled:
            missing = [
                env_name
                for env_name, field_name in _REQUIRED_CREDENTIALS
                if not getattr(self, field_name)
            ]
            if missing:
                raise SettingsError(
                    f"FEISHU_ENABLED=true 时缺少必需配置: {', '.join(missing)}"
                )
            if self.feishu_instance_count > 1:
                self._assert_multi_instance_ready()
        if self.feishu_router_timeout_seconds <= 0:
            raise SettingsError("FEISHU_ROUTER_TIMEOUT_SECONDS 必须大于 0")
        if self.feishu_router_enabled:
            targets = self.router_target_urls()
            if not targets:
                raise SettingsError(
                    "FEISHU_ROUTER_ENABLED=true 时必须配置 FEISHU_ROUTER_INSTANCE_URLS"
                    "（逗号分隔的实例基址，顺序即分片下标 0..N-1）"
                )
            if len(targets) != self.feishu_instance_count:
                raise SettingsError(
                    f"FEISHU_ROUTER_INSTANCE_URLS 个数（{len(targets)}）必须等于"
                    f" FEISHU_INSTANCE_COUNT（{self.feishu_instance_count}）"
                )
            for url in targets:
                if not url.startswith(("http://", "https://")):
                    raise SettingsError(
                        "FEISHU_ROUTER_INSTANCE_URLS 每项必须以 http:// 或 https:// 开头"
                    )
        if not self.feishu_encrypt_key:
            logger.warning(
                "FEISHU_ENCRYPT_KEY 为空: 仅接受未加密事件且不校验签名，安全性降级"
            )
        return self

    def router_target_urls(self) -> tuple[str, ...]:
        """`FEISHU_ROUTER_INSTANCE_URLS` 解析为元组；顺序即分片下标。"""
        return tuple(
            item.strip().rstrip("/")
            for item in self.feishu_router_instance_urls.split(",")
            if item.strip()
        )

    def _assert_multi_instance_ready(self) -> None:
        """多实例就绪契约（FEISHU-011 方案 C）。

        开多实例必须**显式声明**两件事，缺一即启动期失败：

        1. `FEISHU_INGRESS_SHARDED_ROUTING_ENABLED=true` —— ingress 已按
           `crc32(open_id) % FEISHU_INSTANCE_COUNT` 把同会话事件恒定送到同一实例
           （方案 C 的会话串行来源）；
        2. `FEISHU_DEDUPE_PERSISTENT_ENABLED=true` —— 跨进程去重，作为 ingress
           配错时的**兜底**：即使同一 `event_id` 被两个实例收到，也只有一次会真正处理。

        理由：未声明的多实例会让同一会话被多个实例交错处理、状态竞态写，且故障
        偶发（需同时满足同会话 + 跨实例 + 时间重叠）、极难定位。
        """
        missing = [
            name
            for name, ok in (
                (
                    "FEISHU_INGRESS_SHARDED_ROUTING_ENABLED（或 FEISHU_ROUTER_ENABLED）",
                    self.feishu_ingress_sharded_routing_enabled or self.feishu_router_enabled,
                ),
                (
                    "FEISHU_DEDUPE_PERSISTENT_ENABLED",
                    self.feishu_dedupe_persistent_enabled,
                ),
            )
            if not ok
        ]
        if not missing:
            return
        raise SettingsError(
            f"FEISHU_ENABLED=true 且 FEISHU_INSTANCE_COUNT={self.feishu_instance_count}"
            f">1 时，多实例就绪契约未满足，缺少: {', '.join(missing)}。"
            "多实例的会话串行依赖 ingress 按会话分片分流，跨进程去重作为路由配错时的兜底；"
            "两者都必须显式开启。选型与做法见 "
            "docs/integrations/feishu/multi-instance-options.md 方案 C。"
        )

    def secret_values(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in (
                self.feishu_app_secret,
                self.feishu_verification_token,
                self.feishu_encrypt_key,
            )
            if value
        )
