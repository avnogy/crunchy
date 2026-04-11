from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Request

from app.jellyfin import JellyfinClient
from app.web.items import normalize_item

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/")
async def home(request: Request):
    settings = request.app.state.settings
    templates = request.app.state.templates
    logger.debug("Rendering home page")
    client = JellyfinClient(settings)
    try:
        data = await client.get_library()
        items = [
            normalize_item(item, settings.jellyfin_api_url)
            for item in data.get("Items", [])
        ]
        logger.info("Loaded home library with %d items", len(items))
    except httpx.HTTPError:
        logger.warning("Failed to load home library from Jellyfin")
        items = []

    return templates.TemplateResponse(
        "home/index.html",
        {"request": request, "library_items": items, "active_page": "home"},
    )
