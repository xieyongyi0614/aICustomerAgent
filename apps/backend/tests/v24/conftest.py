"""tests/v24 共享夹具：V2.4.0 开关环境与工具注册表单例重置。"""

import pytest

from app.core.settings import get_settings
from app.services.tool import registry as tool_registry


@pytest.fixture(autouse=True)
def _pin_v24_tool_env(monkeypatch):
    """目录级隔离：工具系统开关取默认（总闸 off、运行期禁用清单为空），用例内可显式覆盖。"""
    monkeypatch.setenv("V24_TOOL_SYSTEM_ENABLED", "false")
    monkeypatch.setenv("V24_TOOL_DISABLED_IDS", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def v24_tool_env(monkeypatch):
    """按需注入 V24_* 环境开关，并保证用例结束后 settings 缓存与注册表单例干净。"""
    monkeypatch.setattr(tool_registry, "_registry", None)

    def _apply(**envs):
        for key, value in envs.items():
            text = str(value).lower() if isinstance(value, bool) else str(value)
            monkeypatch.setenv(key.upper(), text)
        get_settings.cache_clear()

    yield _apply
    get_settings.cache_clear()
