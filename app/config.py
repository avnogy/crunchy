from __future__ import annotations

import json
import logging
import os
import secrets
import shlex
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    jellyfin_api_url: str = ""
    jellyfin_api_key: str = ""
    jellyfin_user_id: str = ""
    app_password: str = ""
    transcoding_temp_dir: Path = Path("/data/temp")
    output_dir: Path = Path("/data/output")
    jobs_poll_interval_ms: int = 3000
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    presets: dict = field(default_factory=dict)
    ffmpeg_flags: list[str] = field(default_factory=list)
    redis_host: str = "redis"
    redis_port: int = 6379

    def to_dict(self) -> dict:
        return {
            "jellyfin_api_url": self.jellyfin_api_url,
            "jellyfin_api_key": self.jellyfin_api_key,
            "jellyfin_user_id": self.jellyfin_user_id,
            "transcoding_temp_dir": str(self.transcoding_temp_dir),
            "output_dir": str(self.output_dir),
            "jobs_poll_interval_ms": self.jobs_poll_interval_ms,
            "app_host": self.app_host,
            "app_port": self.app_port,
            "log_level": self.log_level,
            "presets": self.presets,
            "ffmpeg_flags": self.ffmpeg_flags,
            "redis_host": self.redis_host,
            "redis_port": self.redis_port,
        }

    def to_persisted_dict(self) -> dict:
        data = self.to_dict()
        data["app_password"] = self.app_password
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        return cls(
            jellyfin_api_url=str(data.get("jellyfin_api_url", "")).rstrip("/"),
            jellyfin_api_key=data.get("jellyfin_api_key", ""),
            jellyfin_user_id=data.get("jellyfin_user_id", ""),
            app_password=data.get("app_password", ""),
            transcoding_temp_dir=Path(data.get("transcoding_temp_dir", "/data/temp")),
            output_dir=Path(data.get("output_dir", "/data/output")),
            jobs_poll_interval_ms=int(data.get("jobs_poll_interval_ms", 3000)),
            app_host=data.get("app_host", "0.0.0.0"),
            app_port=int(data.get("app_port", 8000)),
            log_level=data.get("log_level", "INFO"),
            presets=data.get("presets", {}),
            ffmpeg_flags=_parse_ffmpeg_flags(data.get("ffmpeg_flags", [])),
            redis_host=data.get("redis_host", os.getenv("REDIS_HOST", "redis")),
            redis_port=int(data.get("redis_port", os.getenv("REDIS_PORT", "6379"))),
        )


def _parse_ffmpeg_flags(value: list[str] | str | None) -> list[str]:
    if isinstance(value, list):
        return [str(flag) for flag in value if str(flag).strip()]
    if isinstance(value, str):
        return shlex.split(value)
    return []


def _get_settings_path() -> Path:
    return Path(os.getenv("SETTINGS_FILE", "/config/settings.json"))


def generate_app_password(length: int = 24) -> str:
    return secrets.token_urlsafe(length)[:length]


def load_settings() -> Settings:
    path = _get_settings_path()

    if path.exists():
        try:
            settings = Settings.from_dict(json.loads(path.read_text()))
            if not settings.app_password:
                settings.app_password = os.getenv("APP_PASSWORD", "")
            return settings
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to load settings from %s: %s", path, e)

    return Settings(
        jellyfin_api_url=os.getenv("JELLYFIN_API_URL", "").rstrip("/"),
        jellyfin_api_key=os.getenv("JELLYFIN_API_KEY", ""),
        jellyfin_user_id=os.getenv("JELLYFIN_USER_ID", ""),
        app_password=os.getenv("APP_PASSWORD", ""),
        transcoding_temp_dir=Path(os.getenv("TRANSCODING_TEMP_DIR", "/data/temp")),
        output_dir=Path(os.getenv("OUTPUT_DIR", "/data/output")),
        jobs_poll_interval_ms=int(os.getenv("JOBS_POLL_INTERVAL_MS", "3000")),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=int(os.getenv("APP_PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        ffmpeg_flags=_parse_ffmpeg_flags(os.getenv("FFMPEG_FLAGS", "")),
        redis_host=os.getenv("REDIS_HOST", "redis"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
    )


def save_settings(settings: Settings) -> None:
    path = _get_settings_path()
    serialized = json.dumps(settings.to_persisted_dict(), indent=2)
    temp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as tmp:
            tmp.write(serialized)
            tmp.flush()
            os.fsync(tmp.fileno())
            temp_path = Path(tmp.name)
        os.replace(temp_path, path)
    except Exception as e:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        logger.error("Failed to save settings to %s: %s", path, e)
        raise


def ensure_app_password(settings: Settings) -> None:
    if settings.app_password:
        if not _get_settings_path().exists():
            save_settings(settings)
        return

    settings.app_password = generate_app_password()
    logger.critical(
        "APP_PASSWORD was not set and no saved app password was found. Generated startup password for admin user: %s",
        settings.app_password,
    )
    save_settings(settings)
    logger.info("Persisted generated app password to %s", _get_settings_path())
