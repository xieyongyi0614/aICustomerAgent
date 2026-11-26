"""ID 生成域设置：雪花 epoch、机器位、跨重启水位防护参数。"""

import datetime as dt

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError

MACHINE_ID_MAX = (1 << 10) - 1


class IdsSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    ids_epoch_date: str = "2026-01-01"
    ids_machine_id: int = 0
    ids_high_water_key: str = "ids:high_water_ms"
    ids_high_water_flush_seconds: int = 5
    ids_clock_rollback_tolerance_ms: int = 0

    @model_validator(mode="after")
    def validate_ids_config(self):
        try:
            epoch = dt.date.fromisoformat(self.ids_epoch_date)
        except ValueError as exc:
            raise SettingsError(f"IDS_EPOCH_DATE 必须是 ISO 日期：{exc}") from exc
        if epoch > dt.date.today():
            raise SettingsError("IDS_EPOCH_DATE 不能晚于今天（epoch 未来化会压缩可用年限）")
        if not 0 <= self.ids_machine_id <= MACHINE_ID_MAX:
            raise SettingsError(f"IDS_MACHINE_ID 必须在 [0, {MACHINE_ID_MAX}]")
        if not self.ids_high_water_key.strip():
            raise SettingsError("IDS_HIGH_WATER_KEY 不能为空")
        if self.ids_high_water_flush_seconds < 1:
            raise SettingsError("IDS_HIGH_WATER_FLUSH_SECONDS 必须 >= 1")
        if self.ids_clock_rollback_tolerance_ms < 0:
            raise SettingsError("IDS_CLOCK_ROLLBACK_TOLERANCE_MS 必须 >= 0")
        return self

    def ids_epoch_datetime(self) -> dt.datetime:
        return dt.datetime.fromisoformat(self.ids_epoch_date).replace(tzinfo=dt.UTC)

    def ids_high_water_storage_key(self) -> str:
        return f"{self.ids_high_water_key}:{self.ids_machine_id}"
