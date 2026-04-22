from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlencode

from pathvalidate import sanitize_filename

from app.config import Settings
from app.jellyfin import JellyfinClient
from app.jobs import Job, JobStore, Progress
from app.paths import OUTPUT_DIR, TRANSCODING_TEMP_DIR
from app.presets import Preset

logger = logging.getLogger(__name__)


def _safe_output_name(name: str) -> str:
    sanitized = sanitize_filename(name, replacement_text="_").strip("._")
    return sanitized or "job"


def build_output_path(job: Job) -> Path:
    return OUTPUT_DIR / f"{job.id}_{_safe_output_name(job.item_name)}.mp4"


def get_ffmpeg_command(
    settings: Settings,
    input_url: str = "https://jellyfin.example/main.m3u8?args=values",
    output_path: str = OUTPUT_DIR / "output.mp4",
    progress_file: str = TRANSCODING_TEMP_DIR / "preview.progress",
) -> list[str]:
    args = [
        "ffmpeg",
        "-y",
        "-i",
        input_url,
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-loglevel",
        "info",
        "-report",
        "-progress",
        str(progress_file),
        "-nostats",
        "-stats_period",
        str(settings.jobs_poll_interval_ms / 1000),
    ]

    args.extend(settings.ffmpeg_flags)
    args.append(str(output_path))
    return args


def _build_transcode_url(
    settings: Settings, job: Job, source_id: str, audio_stream_index: int | None = None
) -> str:
    url = f"{settings.jellyfin_api_url}/Videos/{job.item_id}/main.m3u8"
    preset = Preset(**job.preset)
    params = {
        "api_key": settings.jellyfin_api_key,
        "playSessionId": job.id,
        "mediaSourceId": source_id,
        "videoCodec": preset.videoCodec,
        "audioCodec": preset.audioCodec,
        "videoBitrate": str(preset.videoBitrate),
        "audioBitrate": str(preset.audioBitrate),
        "maxHeight": str(preset.maxHeight),
        "segmentContainer": preset.segmentContainer,
        "transcodeReasons": "ContainerNotSupported",
    }

    if audio_stream_index is not None:
        params["audioStreamIndex"] = str(audio_stream_index)

    return f"{url}?{urlencode(params)}"


async def enqueue_job(
    job: Job, settings: Settings, store: JobStore, audio_stream_index: int | None = None
) -> Job:
    logger.info("Enqueuing job %s: %s", job.id, job.item_name)

    client = JellyfinClient(settings)
    pb_info = await client.get_playback_info(job.item_id)
    sources = pb_info.get("MediaSources", [])
    if not sources:
        raise ValueError("No playable media sources found")

    source_id = sources[0].get("Id")
    if not source_id:
        raise ValueError("No media source ID found")

    run_time_ticks = sources[0].get("RunTimeTicks")
    if run_time_ticks:
        try:
            job.progress.duration = int(run_time_ticks) / 10_000_000
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring invalid RunTimeTicks for job %s: %r",
                job.id,
                run_time_ticks,
            )

    input_url = _build_transcode_url(
        settings, job, source_id, audio_stream_index=audio_stream_index
    )
    output_path = build_output_path(job)
    job.input_url = input_url

    await store.add(job)
    logger.info("Job %s enqueued successfully to Redis", job.id)
    return job
