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
from app.settings_service import ensure_allowed_ffmpeg_flags

logger = logging.getLogger(__name__)


def _safe_output_name(name: str) -> str:
    sanitized = sanitize_filename(name, replacement_text="_").strip("._")
    return sanitized or "job"


def _format_bitrate(preset: Preset) -> str:
    return f"{int(preset.videoBitrate / 1000)}kbps"


def _format_quality(preset: Preset) -> str:
    return f"{preset.maxHeight}p"


def _episode_code(item: dict) -> str:
    season = item.get("ParentIndexNumber")
    episode = item.get("IndexNumber")
    if isinstance(season, int) and isinstance(episode, int):
        return f"S{season:02d}E{episode:02d}"
    if isinstance(episode, int):
        return f"E{episode:02d}"
    return "Episode"


def _build_output_stem(job: Job, item: dict) -> str:
    preset = Preset(**job.preset)
    quality = _format_quality(preset)
    bitrate = _format_bitrate(preset)
    item_type = item.get("Type")

    if item_type == "Episode":
        episode_code = _episode_code(item)
        episode_name = item.get("Name") or job.item_name
        return _safe_output_name(f"{episode_code} {episode_name} {quality} {bitrate}")

    title = item.get("Name") or job.item_name
    return _safe_output_name(f"{title} {quality} {bitrate}")


def build_output_path(job: Job, item: dict) -> Path:
    stem = _build_output_stem(job, item)
    return OUTPUT_DIR / f"{stem} {job.id}.mp4"


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
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0?",
        "-map",
        "0:s?",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-c:s",
        "mov_text",
        "-movflags",
        "+faststart",
        "-loglevel",
        "info",
        "-progress",
        str(progress_file),
        "-nostats",
        "-stats_period",
        str(settings.jobs_poll_interval_ms / 1000),
    ]

    # Saved settings may predate validation or have been edited manually.
    ensure_allowed_ffmpeg_flags(settings.ffmpeg_flags)
    args.extend(settings.ffmpeg_flags)
    args.append(str(output_path))
    return args


def _build_transcode_url(settings: Settings, job: Job, source_id: str) -> str:
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

    if job.audio_stream_index is not None:
        params["audioStreamIndex"] = str(job.audio_stream_index)
    if job.subtitle_stream_index is not None:
        params["subtitleStreamIndex"] = str(job.subtitle_stream_index)
        params["subtitleMethod"] = "Hls"
        params["alwaysBurnInSubtitleWhenTranscoding"] = "true"
        params["transcodeReasons"] = "ContainerNotSupported,SubtitleCodecNotSupported"

    return f"{url}?{urlencode(params)}"


async def enqueue_job(job: Job, settings: Settings, store: JobStore) -> Job:
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

    input_url = _build_transcode_url(settings, job, source_id)
    job.input_url = input_url

    updated_job = await store.update(
        job.id,
        input_url=input_url,
        progress=job.progress,
    )
    if updated_job is not None:
        job = updated_job
    logger.info("Job %s enqueued successfully to Redis", job.id)
    return job
