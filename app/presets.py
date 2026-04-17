from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from pydantic import BaseModel
from typing import Any


class Preset(BaseModel):
    videoCodec: str = "h265"
    audioCodec: str = "aac"
    segmentContainer: str = "mp4"
    maxHeight: int = 720
    videoBitrate: int = 1400000
    audioBitrate: int = 128000
    name: str = "Custom"


def get_effective_presets(presets: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    if not isinstance(presets, Mapping):
        return deepcopy(DEFAULT_PRESETS)
    return {k: Preset(**p).model_dump() for k, p in presets.items() if isinstance(k, str)} or deepcopy(DEFAULT_PRESETS)


NEW_PRESET_TEMPLATE: dict[str, Any] = Preset().model_dump()

DEFAULT_PRESETS: dict[str, dict[str, Any]] = {
    "480p-low": {"maxHeight": 480, "videoBitrate": 800000, "audioBitrate": 64000, "name": "480p Low", "videoCodec": "h265", "audioCodec": "aac", "segmentContainer": "mp4"},
    "480p-medium": {"maxHeight": 480, "videoBitrate": 1200000, "audioBitrate": 96000, "name": "480p Medium", "videoCodec": "h265", "audioCodec": "aac", "segmentContainer": "mp4"},
    "480p-high": {"maxHeight": 480, "videoBitrate": 1600000, "audioBitrate": 128000, "name": "480p High", "videoCodec": "h265", "audioCodec": "aac", "segmentContainer": "mp4"},
    "720p-low": {"maxHeight": 720, "videoBitrate": 1400000, "audioBitrate": 96000, "name": "720p Low", "videoCodec": "h265", "audioCodec": "aac", "segmentContainer": "mp4"},
    "720p-medium": {"maxHeight": 720, "videoBitrate": 2000000, "audioBitrate": 128000, "name": "720p Medium", "videoCodec": "h265", "audioCodec": "aac", "segmentContainer": "mp4"},
    "720p-high": {"maxHeight": 720, "videoBitrate": 2800000, "audioBitrate": 128000, "name": "720p High", "videoCodec": "h265", "audioCodec": "aac", "segmentContainer": "mp4"},
    "1080p-low": {"maxHeight": 1080, "videoBitrate": 2600000, "audioBitrate": 96000, "name": "1080p Low", "videoCodec": "h265", "audioCodec": "aac", "segmentContainer": "mp4"},
    "1080p-medium": {"maxHeight": 1080, "videoBitrate": 3600000, "audioBitrate": 128000, "name": "1080p Medium", "videoCodec": "h265", "audioCodec": "aac", "segmentContainer": "mp4"},
    "1080p-high": {"maxHeight": 1080, "videoBitrate": 5000000, "audioBitrate": 160000, "name": "1080p High", "videoCodec": "h265", "audioCodec": "aac", "segmentContainer": "mp4"},
}