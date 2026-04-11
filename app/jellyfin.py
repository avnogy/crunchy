from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class JellyfinClient:
    def __init__(self, settings: Settings) -> None:
        self._url = settings.jellyfin_api_url
        self._headers = {"X-Emby-Token": settings.jellyfin_api_key}
        self._user_id = settings.jellyfin_user_id

    async def get_library(self) -> dict[str, Any]:
        return await self._get(
            f"/Users/{self._user_id}/Items",
            {
                "Recursive": "true",
                "IncludeItemTypes": "Movie,Series",
                "Fields": "Overview",
            },
        )

    async def get_item(self, item_id: str) -> dict[str, Any]:
        return await self._get(f"/Users/{self._user_id}/Items/{item_id}")

    async def get_children(
        self,
        parent_id: str,
        include_item_types: str | None = None,
        fields: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {"ParentId": parent_id}
        if include_item_types:
            params["IncludeItemTypes"] = include_item_types
        if fields:
            params["Fields"] = fields
        data = await self._get(f"/Users/{self._user_id}/Items", params)
        return data.get("Items", [])

    async def get_season_episodes(
        self,
        series_id: str,
        season_number: int | None = None,
    ) -> list[dict[str, Any]]:
        fields = "Overview,IndexNumber,ParentIndexNumber,MediaSources,SeasonId"
        if season_number is None:
            return []

        data = await self._get(
            f"/Users/{self._user_id}/Items",
            {
                "ParentId": series_id,
                "Recursive": "true",
                "IncludeItemTypes": "Episode",
                "ParentIndexNumber": str(season_number),
                "Fields": fields,
            },
        )
        return data.get("Items", [])

    async def get_playback_info(self, item_id: str) -> dict[str, Any]:
        return await self._post(
            f"/Items/{item_id}/PlaybackInfo",
            {"UserId": self._user_id, "AutoOpenLiveStream": False},
        )

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict:
        logger.debug("Jellyfin GET %s params=%s", path, params)
        async with httpx.AsyncClient(
            base_url=self._url, headers=self._headers, timeout=20
        ) as client:
            response = await client.get(path, params=params)
            logger.debug("Jellyfin GET %s -> %s", path, response.status_code)
            response.raise_for_status()
            if not response.text:
                return {}
            return response.json()

    async def _post(self, path: str, json: dict[str, Any] | None = None) -> dict:
        logger.debug("Jellyfin POST %s", path)
        async with httpx.AsyncClient(
            base_url=self._url, headers=self._headers, timeout=20
        ) as client:
            response = await client.post(path, json=json)
            logger.debug("Jellyfin POST %s -> %s", path, response.status_code)
            response.raise_for_status()
            if not response.text:
                return {}
            return response.json()
