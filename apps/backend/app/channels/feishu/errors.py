"""飞书渠道错误：层级 + retryable 类属性 + 全项目唯一的 HTTP→错误分类入口。"""

from __future__ import annotations


class FeishuError(Exception):
    retryable: bool = False

    def __init__(
        self,
        operation: str,
        http_status: int | None = None,
        feishu_code: int | None = None,
        detail: str = "",
    ):
        self.operation = operation
        self.http_status = http_status
        self.feishu_code = feishu_code
        message = f"feishu {operation} failed (status={http_status}, code={feishu_code})"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


class FeishuDisabledError(FeishuError):
    pass


class FeishuConfigError(FeishuError):
    pass


class FeishuAuthError(FeishuError):
    pass


class FeishuClientError(FeishuError):
    pass


class FeishuRateLimitError(FeishuError):
    retryable = True


class FeishuServerError(FeishuError):
    retryable = True


class FeishuTimeoutError(FeishuError):
    retryable = True


_AUTH_FEISHU_CODES = frozenset({99991661, 99991663, 99991664, 99991668, 10003})


def classify(
    operation: str,
    http_status: int | None = None,
    feishu_code: int | None = None,
    exc: Exception | None = None,
) -> FeishuError:
    if isinstance(exc, FeishuError):
        return exc
    if exc is not None:
        return FeishuTimeoutError(operation, detail=type(exc).__name__)
    if http_status == 429:
        return FeishuRateLimitError(operation, http_status, feishu_code)
    if http_status is not None and http_status >= 500:
        return FeishuServerError(operation, http_status, feishu_code)
    if http_status in (401, 403):
        return FeishuAuthError(operation, http_status, feishu_code)
    if http_status is not None and 200 <= http_status < 300:
        if feishu_code in _AUTH_FEISHU_CODES:
            return FeishuAuthError(operation, http_status, feishu_code)
        return FeishuConfigError(operation, http_status, feishu_code)
    if http_status is not None and 400 <= http_status < 500:
        return FeishuClientError(operation, http_status, feishu_code)
    return FeishuConfigError(operation, http_status, feishu_code)
