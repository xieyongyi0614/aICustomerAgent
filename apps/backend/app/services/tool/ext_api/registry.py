"""外部 API 的模块级单例与 getter（TOOL-011 §3 反模式警示：进程内存态，重启后由声明文件重建）。"""

from __future__ import annotations

from app.services.tool.ext_api.handlers import (
    ExternalApiCapability,
    HttpTransport,
    UrllibTransport,
)
from app.services.tool.ext_api.schema import LoadReport, ManifestIndex, ToolManifestLoader

_index = ManifestIndex()

_capability: ExternalApiCapability | None = None

_loader: ToolManifestLoader | None = None

_transport: HttpTransport | None = None


def get_manifest_index() -> ManifestIndex:
    """模块级清单索引（进程内存态：重启后由声明文件重建，§3 反模式警示）。"""
    return _index


def get_external_api_capability() -> ExternalApiCapability:
    global _capability
    if _capability is None:
        _capability = ExternalApiCapability()
    return _capability


def get_manifest_loader() -> ToolManifestLoader:
    global _loader
    if _loader is None:
        _loader = ToolManifestLoader()
    return _loader


def get_http_transport() -> HttpTransport:
    global _transport
    if _transport is None:
        _transport = UrllibTransport()
    return _transport


def set_http_transport(transport: HttpTransport | None) -> None:
    """测试接缝：注入传输替身；`None` 表示恢复默认 urllib 实现。"""
    global _transport
    _transport = transport


def reset_external_api_state() -> None:
    """进程态归零（测试与热修用）：清单索引 + 加载报告 + 能力单例 + 传输替身。"""
    global _capability, _loader, _transport
    _index.clear()
    _capability = None
    _loader = None
    _transport = None


def last_load_report() -> LoadReport:
    return get_manifest_loader().last_report()
