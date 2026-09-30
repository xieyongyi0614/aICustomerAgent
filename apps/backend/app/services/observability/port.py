"""observability 端口：services 侧只读门面，实现由组合根注册。

分层纪律：services 禁止 import `app.application`。`app.main` lifespan 与测试
conftest 注册 `app.application.observability` 后，消费方经本模块访问，属性在
调用期惰性解析。
"""

_impl = None


def register_observability(impl) -> None:
    global _impl
    _impl = impl


def get_observability():
    if _impl is None:
        raise RuntimeError("observability 端口未注册（app.main lifespan / 测试 conftest）")
    return _impl


def __getattr__(name: str):
    return getattr(get_observability(), name)
