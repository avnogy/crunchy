from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from urllib.parse import urlencode

from pathvalidate import sanitize_filename

from app.config import Settings
from app.jellyfin import JellyfinClient
from app.jobs import Job, JobState

logger = logging.getLogger(__name__)


def _safe_output_name(name: str) -> str:
    sanitized = sanitize_filename(name, replacement_text="_").strip("._")
    return sanitized or "job"


def create_job_file(job: Job, settings: Settings) -> Path:
    """Create a job file in the shared /jobs directory."""
    job_file_path = settings.jobs_dir / f"{job.id}.txt"
    
    # Build the transcoding URL for the worker
    client = JellyfinClient(settings)
    pb_info = asyncio.run(client.get_playback_info(job.item_id))
    sources = pb_info.get("MediaSources", [])
    if not sources:
        raise ValueError("No playable media sources found")
    
    source_id = sources[0].get("Id")
    input_url = _build_transcode_url(settings, job, source_id)
    
    # Write job configuration to file
    job_config = {
        "url": input_url,
        "preset": job.preset,
        "item_name": job.item_name,
        "item_id": job.item_id,
    }
    
    import json
    with open(job_file_path, "w") as f:
        json.dump(job_config, f)
    
    logger.info("Created job file for job %s: %s", job.id, job_file_path)
    return job_file_path


def _build_transcode_url(settings: Settings, job: Job, source_id: str) -> str:
    url = f"{settings.jellyfin_api_url}/Videos/{job.item_id}/main.m3u8"
    params = {
        "api_key": settings.jellyfin_api_key,
        "playSessionId": str(uuid.uuid4()),
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


async def enqueue_job(job: Job, settings: Settings) -> None:
    """
    Enqueue a job by creating a job file in the shared jobs directory.
    No FFmpeg execution happens in the main service anymore.
    """
    if job.state == JobState.CANCELLED:
        logger.info("Skipping cancelled job %s before enqueue", job.id)
        return

    logger.info("Enqueuing job %s: %s", job.id, job.item_name)
    job.start()

    try:
        job_file_path = create_job_file(job, settings)
        job.state = JobState.QUEUED
        logger.info("Job %s enqueued successfully: %s", job.id, job_file_path)
    except Exception as exc:
        logger.exception("Failed to enqueue job %s: %s", job.id, exc)
        job.fail(str(exc))
