"""账务域设置：币种与阈值参数（禁止 `*_enabled` 功能位）。"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class LedgerSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    ledger_default_currency: str = "CNY"
    ledger_extraction_min_confidence: float = 0.70
    ledger_category_fallback: str = "其他"
    ledger_confirm_threshold_amount: float = 100.0
    ledger_digest_send_time: str = ""
    ledger_alert_near_ratio: float = 0.9
    ledger_alert_daily_spike_ratio: float = 3.0
    ledger_alert_daily_spike_floor_minor: int = 5000
    ledger_alert_monthly_surge_ratio: float = 0.5
    ledger_alert_monthly_surge_floor_minor: int = 20000
