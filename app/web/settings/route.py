from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import Settings, save_settings
from app.logging import setup_logging
from app.presets import NEW_PRESET_TEMPLATE, get_effective_presets
from app.transcode import get_ffmpeg_command

logger = logging.getLogger(__name__)

router = APIRouter()
EXACT_PROTECTED_DIRECTORIES = {
    Path("/"),
}
PROTECTED_SUBTREES = {
    Path("/app"),
    Path("/config"),
}

FFMPEG_RESERVED_FLAGS = {
    "-i",
    "-c",
    "-hide_banner",
    "-loglevel",
    "-movflags",
    "-progress",
    "-stats_period",
}


def build_settings_response(settings: Settings, presets: dict) -> dict:
    data = settings.to_dict()
    data["jellyfin_api_key"] = ""
    data["jellyfin_api_key_length"] = len(settings.jellyfin_api_key or "")
    data["app_password"] = ""
    data["app_password_length"] = len(settings.app_password or "")
    data["presets"] = presets
    data["new_preset_template"] = NEW_PRESET_TEMPLATE
    return data


def validate_managed_directory(path_value: str, field_name: str) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        raise HTTPException(
            status_code=400, detail=f"{field_name} must be an absolute path"
        )

    resolved = path.resolve(strict=False)
    if resolved in EXACT_PROTECTED_DIRECTORIES or resolved in PROTECTED_SUBTREES:
        raise HTTPException(
            status_code=400, detail=f"{field_name} points to a protected path"
        )

    for protected in PROTECTED_SUBTREES:
        if protected in resolved.parents:
            raise HTTPException(
                status_code=400, detail=f"{field_name} must not be inside {protected}"
            )

    return path


def clear_directory_contents(directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    removed = 0
    for child in directory.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    return removed


def validate_ffmpeg_flags(flags: list[str] | str) -> list[str]:
    if isinstance(flags, str):
        flags = flags.split()

    for token in flags:
        if token in FFMPEG_RESERVED_FLAGS:
            logger.warning("Rejected reserved ffmpeg flag: %s", token)
            raise HTTPException(
                status_code=400,
                detail=f"Flag '{token}' is not allowed as it conflicts with required options",
            )

    return flags


@router.get("/api/settings")
async def get_settings(request: Request):
    settings = request.app.state.settings
    logger.debug("Returning settings payload")
    data = build_settings_response(settings, request.app.state.presets)
    return JSONResponse({"settings": data})


@router.get("/api/ffmpeg-command")
async def get_ffmpeg_command_api(request: Request):
    settings = request.app.state.settings
    logger.debug("Generating ffmpeg command preview from saved settings")
    cmd = get_ffmpeg_command(settings)
    return JSONResponse({"command": cmd})


@router.post("/api/ffmpeg-preview")
async def ffmpeg_preview(request: Request, payload: dict):
    flags = validate_ffmpeg_flags(payload.get("ffmpeg_flags", []))
    logger.debug("Building ffmpeg preview with %d custom flag token(s)", len(flags))
    cmd = get_ffmpeg_command(Settings(ffmpeg_flags=flags))
    logger.debug("Returning ffmpeg preview command with %d argument(s)", len(cmd))
    return JSONResponse({"command": cmd})


@router.post("/api/settings")
async def update_settings(request: Request, data: dict):
    settings = request.app.state.settings
    logger.info("Updating settings")

    if "jellyfin_api_key" in data and data.get("jellyfin_api_key"):
        settings.jellyfin_api_key = data["jellyfin_api_key"]
    if "jellyfin_api_url" in data:
        settings.jellyfin_api_url = data["jellyfin_api_url"]
    if "jellyfin_user_id" in data:
        settings.jellyfin_user_id = data["jellyfin_user_id"]
    if "app_password" in data and data.get("app_password"):
        settings.app_password = data["app_password"]
    if "transcoding_temp_dir" in data and data["transcoding_temp_dir"]:
        settings.transcoding_temp_dir = validate_managed_directory(
            data["transcoding_temp_dir"], "transcoding_temp_dir"
        )
    if "output_dir" in data and data["output_dir"]:
        settings.output_dir = validate_managed_directory(
            data["output_dir"], "output_dir"
        )
    if "app_host" in data:
        settings.app_host = data["app_host"]
    if "app_port" in data and data["app_port"] is not None:
        settings.app_port = int(data["app_port"])
    if data.get("jobs_poll_interval_ms") is not None:
        settings.jobs_poll_interval_ms = max(500, int(data["jobs_poll_interval_ms"]))
    if "log_level" in data and data["log_level"]:
        settings.log_level = data["log_level"]
        setup_logging(data["log_level"])
        logger.info("Log level updated to %s", data["log_level"])
        logger.debug("Debug logging is now enabled")
        logger.warning("Warning logging remains enabled")
    if "presets" in data:
        canonical_presets = get_effective_presets(data["presets"])
        settings.presets = canonical_presets
        request.app.state.presets = canonical_presets
    if "ffmpeg_flags" in data:
        settings.ffmpeg_flags = validate_ffmpeg_flags(data["ffmpeg_flags"])

    save_settings(settings)
    logger.info(
        "Settings saved host=%s port=%s poll_interval_ms=%s",
        settings.app_host,
        settings.app_port,
        settings.jobs_poll_interval_ms,
    )
    response_settings = build_settings_response(settings, request.app.state.presets)
    return JSONResponse({"settings": response_settings})


@router.post("/api/settings/clear-temp")
async def clear_temp_directory(request: Request):
    settings = request.app.state.settings
    logger.warning("Clearing temp directory %s", settings.transcoding_temp_dir)
    removed = clear_directory_contents(settings.transcoding_temp_dir)
    logger.info(
        "Cleared temp directory %s removed=%d", settings.transcoding_temp_dir, removed
    )
    return JSONResponse(
        {"cleared": removed, "path": str(settings.transcoding_temp_dir)}
    )


@router.post("/api/settings/clear-output")
async def clear_output_directory(request: Request):
    settings = request.app.state.settings
    logger.warning("Clearing output directory %s", settings.output_dir)
    removed = clear_directory_contents(settings.output_dir)
    logger.info("Cleared output directory %s removed=%d", settings.output_dir, removed)
    return JSONResponse({"cleared": removed, "path": str(settings.output_dir)})


@router.get("/settings")
async def settings_page(request: Request):
    templates = request.app.state.templates
    logger.debug("Rendering settings page")
    return templates.TemplateResponse(
        "settings/index.html",
        {"request": request, "active_page": "settings"},
    )
