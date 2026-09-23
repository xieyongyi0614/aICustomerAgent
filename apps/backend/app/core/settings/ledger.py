"""账务域设置：币种与阈值参数（禁止 `*_enabled` 功能位）。"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class LedgerSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    ledger_default_currency: str = "CNY"
    ledger_extraction_min_confidence: float = 0.70
    ledger_category_fallback: str = "其他"
    ledger_confirm_threshold_amount: float = 100.0
