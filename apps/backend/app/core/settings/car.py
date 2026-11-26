"""车辆域设置：提醒提前量（参数类，禁止 `*_enabled` 功能位）。"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class CarSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    car_service_remind_km_before: int = 3000
    car_service_remind_days_before: int = 45
    car_insurance_remind_days_before: int = 60
    car_inspection_remind_days_before: int = 30
