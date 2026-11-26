"""应用版本与制品域设置：制品根目录与更新说明长度上限（参数类，禁止 `*_enabled` 功能位）。"""

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError


class AppReleaseSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    app_release_storage_dir: str = "/srv/backend/releases"
    app_release_notes_max_chars: int = 2000

    @model_validator(mode="after")
    def _validate_storage_and_notes(self) -> "AppReleaseSettings":
        if not self.app_release_storage_dir.strip():
            raise SettingsError("APP_RELEASE_STORAGE_DIR 不能为空")
        if self.app_release_notes_max_chars < 1:
            raise SettingsError("APP_RELEASE_NOTES_MAX_CHARS 必须至少为 1")
        return self
