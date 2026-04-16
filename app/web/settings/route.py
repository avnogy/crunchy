from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import save_settings
from app.logging import setup_logging
from app.presets import normalize_presets
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


@router.get("/api/settings")
async def get_settings(request: Request):
    settings = request.app.state.settings
    presets = request.app.state.presets
    logger.debug("Returning settings payload")
    data = settings.to_dict()
    data["jellyfin_api_key"] = ""
    data["jellyfin_api_key_length"] = len(settings.jellyfin_api_key or "")
    data["app_password"] = ""
    data["app_password_length"] = len(settings.app_password or "")
    data["presets"] = presets
    return JSONResponse({"settings": data})


@router.get("/api/ffmpeg-command")
async def get_ffmpeg_command_api(request: Request):
    settings = request.app.state.settings
    logger.debug("Generating ffmpeg command preview from saved settings")
    cmd = get_ffmpeg_command(settings)
    return JSONResponse({"command": cmd})


@router.post("/api/ffmpeg-preview")
async def ffmpeg_preview(request: Request, payload: dict):
    """Return the FFmpeg command based on temporary flags sent by the client.
    All other settings are taken from the current server configuration.
    """
    settings = request.app.state.settings
    # Extract flags – accept list or space‑separated string
    flags = payload.get("ffmpeg_flags", [])
    if isinstance(flags, str):
        flags = flags.split()
    logger.debug("Building ffmpeg preview with %d custom flag token(s)", len(flags))
    # Validate flags: disallow options that would override hard‑coded parts of the command
    reserved = {
        "-i",
        "-c",
        "-hide_banner",
        "-loglevel",
        "-movflags",
        "-progress",
        "-stats_period",
    }
    for token in flags:
        if token in reserved:
            logger.warning("Rejected reserved ffmpeg flag in preview: %s", token)
            raise HTTPException(
                status_code=400,
                detail=f"Flag '{token}' is not allowed as it conflicts with required options",
            )
    # Build a fresh Settings instance mirroring the existing one but with overridden flags
    from app.config import Settings

    preview_settings = Settings(
        jellyfin_api_url=settings.jellyfin_api_url,
        jellyfin_api_key=settings.jellyfin_api_key,
        jellyfin_user_id=settings.jellyfin_user_id,
        transcoding_temp_dir=settings.transcoding_temp_dir,
        output_dir=settings.output_dir,
        max_concurrent_jobs=settings.max_concurrent_jobs,
        jobs_poll_interval_ms=settings.jobs_poll_interval_ms,
        app_host=settings.app_host,
        app_port=settings.app_port,
        log_level=settings.log_level,
        presets=settings.presets,
        ffmpeg_flags=flags,
    )
    cmd = get_ffmpeg_command(preview_settings)
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
    if "max_concurrent_jobs" in data and data["max_concurrent_jobs"] is not None:
        settings.max_concurrent_jobs = int(data["max_concurrent_jobs"])
    if data.get("jobs_poll_interval_ms") is not None:
        settings.jobs_poll_interval_ms = max(500, int(data["jobs_poll_interval_ms"]))
    if "log_level" in data and data["log_level"]:
        settings.log_level = data["log_level"]
        setup_logging(data["log_level"])
        logger.info("Log level updated to %s", data["log_level"])
        logger.debug("Debug logging is now enabled")
        logger.warning("Warning logging remains enabled")
    if "presets" in data:
        settings.presets = data["presets"]
        request.app.state.presets = normalize_presets(data["presets"])
    if "ffmpeg_flags" in data:
        # Validate flags: disallow options that would override hard‑coded parts of the command
        reserved = {
            "-i",
            "-c",
            "-hide_banner",
            "-loglevel",
            "-movflags",
            "-progress",
            "-stats_period",
        }
        flags = data["ffmpeg_flags"]
        if isinstance(flags, str):
            flags = flags.split()
        for token in flags:
            if token in reserved:
                logger.warning(
                    "Rejected reserved ffmpeg flag in settings update: %s", token
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"Flag '{token}' is not allowed as it conflicts with required options",
                )
        settings.ffmpeg_flags = flags

    save_settings(settings)
    logger.info(
        "Settings saved host=%s port=%s workers=%s poll_interval_ms=%s",
        settings.app_host,
        settings.app_port,
        settings.max_concurrent_jobs,
        settings.jobs_poll_interval_ms,
    )
    response_settings = settings.to_dict()
    response_settings["jellyfin_api_key"] = ""
    response_settings["jellyfin_api_key_length"] = len(settings.jellyfin_api_key or "")
    response_settings["app_password"] = ""
    response_settings["app_password_length"] = len(settings.app_password or "")
    response_settings["presets"] = request.app.state.presets
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
