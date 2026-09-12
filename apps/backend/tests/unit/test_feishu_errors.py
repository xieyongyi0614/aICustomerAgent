import pytest

from app.channels.feishu import errors as feishu_errors
from app.channels.feishu.errors import (
    FeishuAuthError,
    FeishuClientError,
    FeishuConfigError,
    FeishuDisabledError,
    FeishuError,
    FeishuRateLimitError,
    FeishuServerError,
    FeishuTimeoutError,
    classify,
)

RETRYABLE_EXPECTATIONS = [
    (FeishuDisabledError, False),
    (FeishuConfigError, False),
    (FeishuAuthError, False),
    (FeishuClientError, False),
    (FeishuRateLimitError, True),
    (FeishuServerError, True),
    (FeishuTimeoutError, True),
]


@pytest.mark.parametrize("error_type,expected_retryable", RETRYABLE_EXPECTATIONS)
def test_retryable_is_class_attribute(error_type, expected_retryable):
    assert error_type.retryable is expected_retryable
    error = error_type("op", 500, 1)
    assert error.retryable is expected_retryable


@pytest.mark.parametrize("error_type,expected", RETRYABLE_EXPECTATIONS)
def test_error_hierarchy(error_type, expected):
    assert issubclass(error_type, FeishuError)


def test_error_carries_context_without_secrets():
    error = FeishuServerError("tenant_access_token", 502, 99991400)
    assert error.operation == "tenant_access_token"
    assert error.http_status == 502
    assert error.feishu_code == 99991400
    text = str(error)
    assert "tenant_access_token" in text
    assert "502" in text
    assert "99991400" in text


def test_classify_429():
    error = classify("op", 429, None)
    assert isinstance(error, FeishuRateLimitError)
    assert error.retryable is True


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_classify_5xx(status):
    error = classify("op", status, None)
    assert isinstance(error, FeishuServerError)
    assert error.retryable is True


@pytest.mark.parametrize("exc_factory", [TimeoutError, OSError])
def test_classify_transport_exception_as_timeout(exc_factory):
    error = classify("op", exc=exc_factory())
    assert isinstance(error, FeishuTimeoutError)
    assert error.retryable is True


def test_classify_401_403_auth_not_retryable():
    for status in (401, 403):
        error = classify("op", status, None)
        assert isinstance(error, FeishuAuthError)
        assert error.retryable is False


@pytest.mark.parametrize("code", [10003, 99991661, 99991663, 99991668])
def test_classify_2xx_auth_business_codes(code):
    error = classify("op", 200, code)
    assert isinstance(error, FeishuAuthError)
    assert error.retryable is False


def test_classify_2xx_other_nonzero_code_is_config():
    for code in (99991400, 1, 230001):
        error = classify("op", 200, code)
        assert isinstance(error, FeishuConfigError)
        assert error.retryable is False


@pytest.mark.parametrize("status", [400, 404, 422])
def test_classify_other_4xx_client(status):
    error = classify("op", status, None)
    assert isinstance(error, FeishuClientError)
    assert error.retryable is False


def test_classify_unexpected_defaults_to_config():
    error = classify("op", None, None)
    assert isinstance(error, FeishuConfigError)
    assert error.retryable is False
    redirect = classify("op", 302, None)
    assert isinstance(redirect, FeishuConfigError)


def test_classify_passthrough_feishu_error_instance():
    original = FeishuRateLimitError("op", 429, None)
    assert classify("op", exc=original) is original


def test_classify_is_the_only_mapping_point():
    import inspect

    source = inspect.getsource(feishu_errors)
    assert "def classify" in source
