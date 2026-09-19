"""数据库连接域设置。"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class DatabaseSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    database_url: str = "postgresql+psycopg://asuna:asuna@localhost:5432/asuna"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle: int = 1800
    db_pool_pre_ping: bool = True
    db_statement_timeout_ms: int = 0
