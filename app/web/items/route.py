from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.jellyfin import JellyfinClient

router = APIRouter()
logger = logging.getLogger(__name__)


def normalize_item(
    item: dict[str, Any], image_base_url: str | None = None
) -> dict[str, Any]:
    item_type = item.get("Type")
    result = {
        "id": item.get("Id"),
        "name": item.get("Name"),
        "type": item_type,
        "overview": item.get("Overview", ""),
        "year": item.get("ProductionYear"),
        "season_number": (
            item.get("ParentIndexNumber")
            if item_type == "Episode"
            else item.get("IndexNumber") or item.get("ParentIndexNumber")
        ),
        "episode_number": item.get("IndexNumber") if item_type == "Episode" else None,
    }
    item_id = item.get("Id")
    if item_id and image_base_url:
        result["image"] = (
            f"{image_base_url}/Items/{item_id}/Images/Primary?quality=80&width=400"
        )
    run_time = item.get("RunTimeTicks")
    if run_time:
        result["runtime_seconds"] = int(run_time) / 10_000_000
    media_sources = item.get("MediaSources", [])
    if media_sources:
        result["size_bytes"] = int(media_sources[0].get("Size", 0))
    return result


async def get_item_with_children(
    item_id: str, client: JellyfinClient
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
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
    presets = request.app.state.presets
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
    return templates.TemplateResponse(
        "items/index.html",
        {
            "request": request,
            "item": item,
            "children": [
                normalize_item(c, settings.jellyfin_api_url) for c in children
            ],
            "presets": presets,
            "settings": settings,
            "active_page": "items",
        },
    )
