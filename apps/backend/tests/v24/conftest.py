"""tests/v24 共享夹具：V2.4.0 开关环境与工具/能力注册表单例重置。"""

import pytest

from app.core.settings import get_settings
from app.services.action import registry as capability_registry_module
from app.services.tool import registry as tool_registry
from tests.conftest import set_known_flag_env


@pytest.fixture(autouse=True)
def _pin_v24_tool_env(monkeypatch):
    """目录级隔离：工具系统开关取默认（总闸 off、运行期禁用清单为空），用例内可显式覆盖。"""
    monkeypatch.setenv("V24_TOOL_SYSTEM_ENABLED", "false")
    monkeypatch.setenv("V24_TOOL_DISABLED_IDS", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_capability_registry(monkeypatch):
    """目录级隔离：能力注册表单例用例前归零、用例后恢复进入前的对象。

    V2.4.0 开闸用例（总闸 + 外部面 / 通道子闸）会经 `get_tool_registry()` →
    `builtin._capability_for()` 构建带 `external_api` / `channel_feishu` 的全局注册表；
    该对象若留在 `app.services.action.registry._registry`，会污染同 worker 后续
    `tests/unit` 对"V9 六能力"的断言（xdist 下顺序不定 → 偶发失败）。
    用 monkeypatch 承载"用例前归零 + 用例后还原"，与 `v24_tool_env` 对
    `tool_registry._registry` 的纪律一致。构建期 Flag 快照（P1-1 `_registry_flags`）
    与单例一起归零，避免上一用例的构建期快照泄漏到下一用例。
    """
    monkeypatch.setattr(capability_registry_module, "_registry", None)
    capability_registry_module._registry_flags.clear()
    get_settings.cache_clear()
    yield
    capability_registry_module._registry_flags.clear()
    get_settings.cache_clear()


@pytest.fixture
def v24_tool_env(monkeypatch):
    """按需注入 V24_* 环境开关，并保证用例结束后 settings 缓存与注册表单例干净。"""
    monkeypatch.setattr(tool_registry, "_registry", None)

    def _apply(**envs):
        for key, value in envs.items():
            text = str(value).lower() if isinstance(value, bool) else str(value)
            set_known_flag_env(monkeypatch, key.upper(), text)
        get_settings.cache_clear()

    yield _apply
    get_settings.cache_clear()
