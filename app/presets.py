from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

PRESET_TRANSCODE_DEFAULTS = {
    "videoCodec": "h265",
    "audioCodec": "aac",
    "segmentContainer": "mp4",
}

NEW_PRESET_TEMPLATE = {
    "maxHeight": 720,
    "videoBitrate": 1400000,
    "audioBitrate": 128000,
    "name": "Custom",
    **PRESET_TRANSCODE_DEFAULTS,
}
PRESET_LEVELS = {
    "480p": {
        "low": (800000, 64000),
        "medium": (1200000, 96000),
        "high": (1600000, 128000),
    },
    "720p": {
        "low": (1400000, 96000),
        "medium": (2000000, 128000),
        "high": (2800000, 128000),
    },
    "1080p": {
        "low": (2600000, 96000),
        "medium": (3600000, 128000),
        "high": (5000000, 160000),
    },
}

Preset = dict[str, Any]
PresetCollection = dict[str, Preset]


def with_preset_defaults(preset: Mapping[str, Any] | None = None) -> Preset:
    if not isinstance(preset, Mapping):
        preset = {}

    merged: Preset = {**PRESET_TRANSCODE_DEFAULTS, **preset}
    for key, default in PRESET_TRANSCODE_DEFAULTS.items():
        value = merged.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            merged[key] = default
    return merged


def normalize_presets(presets: Mapping[str, Any] | None) -> PresetCollection:
    if not isinstance(presets, Mapping):
        return {}

    return {
        key: with_preset_defaults(preset)
        for key, preset in presets.items()
        if isinstance(key, str)
    }


def get_effective_presets(presets: Mapping[str, Any] | None) -> PresetCollection:
    normalized = normalize_presets(presets)
    return normalized or deepcopy(DEFAULT_PRESETS)

DEFAULT_PRESETS = {
    f"{height}-{tier}": {
        "maxHeight": int(height.removesuffix("p")),
        "videoBitrate": video_bitrate,
        "audioBitrate": audio_bitrate,
        "name": f"{height} {tier.title()}",
        **PRESET_TRANSCODE_DEFAULTS,
    }
    for height, tiers in PRESET_LEVELS.items()
    for tier, (video_bitrate, audio_bitrate) in tiers.items()
}
