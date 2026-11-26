"""world_engine 端口：services 侧只读门面，实现由组合根注册。

分层纪律：services 禁止 import `app.application`。`app.main` lifespan 与测试
conftest 注册 `app.application.world_engine` 后，消费方经本模块访问，属性在
调用期惰性解析。
"""

_engine = None


def register_world_engine(impl) -> None:
    global _engine
    _engine = impl


def get_world_engine():
    if _engine is None:
        raise RuntimeError("world_engine 端口未注册（app.main lifespan / 测试 conftest）")
    return _engine


def __getattr__(name: str):
    return getattr(get_world_engine(), name)
