from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlencode

from pathvalidate import sanitize_filename

from app.config import Settings
from app.jellyfin import JellyfinClient
from app.jobs import Job, RedisJobStore
from app.presets import PRESET_TRANSCODE_DEFAULTS, with_preset_defaults

logger = logging.getLogger(__name__)


def _safe_output_name(name: str) -> str:
    sanitized = sanitize_filename(name, replacement_text="_").strip("._")
    return sanitized or "job"


def build_output_path(settings: Settings, job: Job) -> Path:
    return settings.output_dir / f"{job.id}_{_safe_output_name(job.item_name)}.mp4"


def get_ffmpeg_command(
    settings: Settings,
    input_url: str = "https://jellyfin.example/stream.m3u8",
    output_path: str = "/data/output/output.mp4",
    preset: dict | None = None,
) -> list[str]:
    resolved_preset = with_preset_defaults(preset)
    args = [
        "ffmpeg",
        "-y",
        "-i",
        input_url,
        "-c:v",
        resolved_preset["videoCodec"],
        "-c:a",
        resolved_preset["audioCodec"],
        "-movflags",
        "+faststart",
    ]

    video_bitrate = int(resolved_preset.get("videoBitrate", 0) or 0)
    audio_bitrate = int(resolved_preset.get("audioBitrate", 0) or 0)
    max_height = int(resolved_preset.get("maxHeight", 0) or 0)

    if video_bitrate > 0:
        args.extend(["-b:v", str(video_bitrate)])
    if audio_bitrate > 0:
        args.extend(["-b:a", str(audio_bitrate)])
    if max_height > 0:
        args.extend(["-vf", f"scale=-2:{max_height}"])

    args.extend(settings.ffmpeg_flags)
    args.append(output_path)
    return args


def _build_transcode_url(settings: Settings, job: Job, source_id: str) -> str:
    url = f"{settings.jellyfin_api_url}/Videos/{job.item_id}/main.m3u8"
    params = {
        "api_key": settings.jellyfin_api_key,
        "playSessionId": job.id,
        "mediaSourceId": source_id,
        "videoCodec": job.preset.get(
            "videoCodec", PRESET_TRANSCODE_DEFAULTS["videoCodec"]
        ),
        "audioCodec": job.preset.get(
            "audioCodec", PRESET_TRANSCODE_DEFAULTS["audioCodec"]
        ),
        "videoBitrate": str(job.preset.get("videoBitrate", 0)),
        "audioBitrate": str(job.preset.get("audioBitrate", 0)),
        "maxHeight": str(job.preset.get("maxHeight", 0)),
        "segmentContainer": job.preset.get(
            "segmentContainer", PRESET_TRANSCODE_DEFAULTS["segmentContainer"]
        ),
        "transcodeReasons": "ContainerNotSupported",
    }
    return f"{url}?{urlencode(params)}"


async def enqueue_job(job: Job, settings: Settings, store: RedisJobStore) -> Job:
    logger.info("Enqueuing job %s: %s", job.id, job.item_name)

    client = JellyfinClient(settings)
    pb_info = await client.get_playback_info(job.item_id)
    sources = pb_info.get("MediaSources", [])
    if not sources:
        raise ValueError("No playable media sources found")

    source_id = sources[0].get("Id")
    if not source_id:
        raise ValueError("No media source ID found")

    input_url = _build_transcode_url(settings, job, source_id)
    output_path = build_output_path(settings, job)
    payload = {
        "job_id": job.id,
        "item_id": job.item_id,
        "item_name": job.item_name,
        "preset": job.preset,
        "input_url": input_url,
        "output_path": str(output_path),
        "created_at": job.created_at,
    }

    store.add(job, payload)
    logger.info("Job %s enqueued successfully to Redis", job.id)
    return job
