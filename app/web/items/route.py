from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.jellyfin import JellyfinClient

router = APIRouter()
logger = logging.getLogger(__name__)


def _extract_audio_streams(media_sources: list[dict]) -> list[dict] | None:
    if not media_sources or not isinstance(media_sources[0], dict):
        return None
    streams = media_sources[0].get("MediaStreams", [])
    if not isinstance(streams, list):
        return None
    audio = []

    for stream in streams:
        if not isinstance(stream, dict):
            continue
        if stream.get("Type") != "Audio":
            continue

        index = stream.get("Index")
        if not isinstance(index, int):
            continue

        title = stream.get("DisplayTitle") or stream.get("Title") or ""
        language = str(stream.get("Language") or "").lower()
        codec = stream.get("Codec") or ""
        audio.append(
            {
                "index": index,
                "language": language,
                "codec": codec,
                "title": title,
                "is_default": bool(stream.get("IsDefault")),
            }
        )

    return audio or None


def _extract_subtitle_streams(media_sources: list[dict]) -> list[dict] | None:
    if not media_sources or not isinstance(media_sources[0], dict):
        return None
    streams = media_sources[0].get("MediaStreams", [])
    if not isinstance(streams, list):
        return None
    subtitles = []

    for stream in streams:
        if not isinstance(stream, dict):
            continue
        if stream.get("Type") != "Subtitle":
            continue

        index = stream.get("Index")
        if not isinstance(index, int):
            continue

        title = stream.get("DisplayTitle") or stream.get("Title") or ""
        language = str(stream.get("Language") or "").lower()
        codec = stream.get("Codec") or ""
        subtitles.append(
            {
                "index": index,
                "language": language,
                "codec": codec,
                "title": title,
                "is_default": bool(stream.get("IsDefault")),
            }
        )

    return subtitles or None


def _apply_audio_streams(item: dict[str, Any], media_sources: list[dict]) -> None:
    audio_streams = _extract_audio_streams(media_sources)
    if audio_streams:
        item["audio_streams"] = audio_streams


def _apply_subtitle_streams(item: dict[str, Any], media_sources: list[dict]) -> None:
    subtitle_streams = _extract_subtitle_streams(media_sources)
    if subtitle_streams:
        item["subtitle_streams"] = subtitle_streams


def normalize_item(item: dict[str, Any], image_base_url: str | None = None) -> dict[str, Any]:
    item_type = item.get("Type")
    result = {
        "id": item.get("Id"),
        "name": item.get("Name"),
        "type": item_type,
        "overview": item.get("Overview", ""),
        "year": item.get("ProductionYear"),
        "season_number": (item.get("ParentIndexNumber") if item_type == "Episode" else item.get("IndexNumber") or item.get("ParentIndexNumber")),
        "episode_number": item.get("IndexNumber") if item_type == "Episode" else None,
    }
    item_id = item.get("Id")
    if item_id and image_base_url:
        result["image"] = f"{image_base_url}/Items/{item_id}/Images/Primary?quality=80&width=960"
    run_time = item.get("RunTimeTicks")
    if run_time:
        try:
            result["runtime_seconds"] = int(run_time) / 10_000_000
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid RunTimeTicks for item %s: %r", item_id, run_time)
    media_sources = item.get("MediaSources", [])
    if isinstance(media_sources, list) and media_sources and isinstance(media_sources[0], dict):
        try:
            result["size_bytes"] = int(media_sources[0].get("Size", 0))
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid media size for item %s", item_id)
        _apply_audio_streams(result, media_sources)
        _apply_subtitle_streams(result, media_sources)
    return result


async def get_item_with_children(item_id: str, client: JellyfinClient) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    children: list[dict[str, Any]] = []
    item: dict[str, Any] | None = None
    try:
        item = await client.get_item(item_id)
        if not item:
            return None, []

        item_type = item.get("Type")
        if item_type == "Season":
            series_id = item.get("SeriesId")
            season_number = item.get("IndexNumber")
            if series_id:
                children = await client.get_season_episodes(series_id, season_number)
        elif item_type == "Series":
            children = await client.get_children(item_id)
    except Exception:
        logger.exception("Failed to load item details for item_id=%s", item_id)
        return None, []
    return item, children


@router.get("/items/{item_id}")
async def item_detail(request: Request, item_id: str):
    settings = request.app.state.settings
    templates = request.app.state.templates
    logger.debug("Rendering item detail for item_id=%s", item_id)
    client = JellyfinClient(settings)
    item, children = await get_item_with_children(item_id, client)
    if not item:
        logger.warning("Item detail unavailable for item_id=%s", item_id)
        raise HTTPException(status_code=502, detail="Failed to fetch item")
    logger.info(
        "Loaded item detail for item_id=%s type=%s children=%d",
        item_id,
        item.get("Type"),
        len(children),
    )

    media_sources = item.get("MediaSources", [])
    if media_sources:
        _apply_audio_streams(item, media_sources)
        _apply_subtitle_streams(item, media_sources)

    return templates.TemplateResponse(
        request,
        "items/index.html",
        {
            "item": item,
            "children": [normalize_item(c, settings.jellyfin_api_url) for c in children],
            "presets": settings.presets,
            "settings": settings,
            "active_page": "items",
        },
    )
