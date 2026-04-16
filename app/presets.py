from __future__ import annotations

PRESET_TRANSCODE_DEFAULTS = {
    "videoCodec": "h265",
    "audioCodec": "aac",
    "segmentContainer": "mp4",
}


def with_preset_defaults(preset: dict | None = None) -> dict:
    return {**PRESET_TRANSCODE_DEFAULTS, **(preset or {})}


def normalize_presets(presets: dict | None) -> dict:
    return {
        key: with_preset_defaults(preset)
        for key, preset in (presets or {}).items()
    }

DEFAULT_PRESETS = {
    "480p-low": {
        "maxHeight": 480,
        "videoBitrate": 800000,
        "audioBitrate": 64000,
        **PRESET_TRANSCODE_DEFAULTS,
        "name": "480p Low",
    },
    "480p-medium": {
        "maxHeight": 480,
        "videoBitrate": 1200000,
        "audioBitrate": 96000,
        **PRESET_TRANSCODE_DEFAULTS,
        "name": "480p Medium",
    },
    "480p-high": {
        "maxHeight": 480,
        "videoBitrate": 1600000,
        "audioBitrate": 128000,
        **PRESET_TRANSCODE_DEFAULTS,
        "name": "480p High",
    },
    "720p-low": {
        "maxHeight": 720,
        "videoBitrate": 1400000,
        "audioBitrate": 96000,
        **PRESET_TRANSCODE_DEFAULTS,
        "name": "720p Low",
    },
    "720p-medium": {
        "maxHeight": 720,
        "videoBitrate": 2000000,
        "audioBitrate": 128000,
        **PRESET_TRANSCODE_DEFAULTS,
        "name": "720p Medium",
    },
    "720p-high": {
        "maxHeight": 720,
        "videoBitrate": 2800000,
        "audioBitrate": 128000,
        **PRESET_TRANSCODE_DEFAULTS,
        "name": "720p High",
    },
    "1080p-low": {
        "maxHeight": 1080,
        "videoBitrate": 2600000,
        "audioBitrate": 96000,
        **PRESET_TRANSCODE_DEFAULTS,
        "name": "1080p Low",
    },
    "1080p-medium": {
        "maxHeight": 1080,
        "videoBitrate": 3600000,
        "audioBitrate": 128000,
        **PRESET_TRANSCODE_DEFAULTS,
        "name": "1080p Medium",
    },
    "1080p-high": {
        "maxHeight": 1080,
        "videoBitrate": 5000000,
        "audioBitrate": 160000,
        **PRESET_TRANSCODE_DEFAULTS,
        "name": "1080p High",
    },
}
