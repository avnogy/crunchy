from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from urllib.parse import urlencode

from pathvalidate import sanitize_filename

from app.config import Settings
from app.jellyfin import JellyfinClient
from app.jobs import Job, JobState
from app.presets import PRESET_TRANSCODE_DEFAULTS

logger = logging.getLogger(__name__)


def _safe_output_name(name: str) -> str:
    sanitized = sanitize_filename(name, replacement_text="_").strip("._")
    return sanitized or "job"


def get_ffmpeg_command(
    settings: Settings,
    input_url: str = "URL",
    output_path: str = "output.mp4",
    progress_file: str = "",
) -> list[str]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        input_url,
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        *settings.ffmpeg_flags,
    ]

    # Add progress file if specified
    if progress_file:
        cmd.extend(["-progress", progress_file])

    cmd.extend(
        [
            "-stats_period",
            str(settings.jobs_poll_interval_ms),
            output_path,
        ]
    )

    return cmd


def cancel_job_artifacts(job: Job) -> None:
    logger.info("Cancelling artifacts for job %s", job.id)
    if job.process:
        job.process.terminate()
        try:
            job.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning(
                "Job %s did not terminate gracefully; killing process", job.id
            )
            job.process.kill()
    if job.output_path and job.output_path.exists():
        logger.debug(
            "Removing partial output for job %s at %s", job.id, job.output_path
        )
        job.output_path.unlink()


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


def _read_progress_from_file(progress_file: Path, job: Job) -> None:
    """
    Read progress information from the ffmpeg progress file and update job progress.
    """

    def update_progress():
        import time

        last_out_time = ""

        time.sleep(0.5)

        while job.state == JobState.RUNNING:
            try:
                if job.process and job.process.poll() is not None:
                    break

                if progress_file.exists():
                    with open(progress_file, "r") as f:
                        content = f.read()
                        lines = content.split("\n")
                        progress_updated = False
                        for line in lines:
                            if line.startswith("out_time="):
                                out_time = line.split("=")[1].strip()
                                if out_time and out_time != last_out_time:
                                    job.progress["current"] = out_time
                                    last_out_time = out_time
                                    progress_updated = True
                            elif line.startswith("progress="):
                                # Check if progress is finished
                                progress_state = line.split("=")[1].strip()
                                if progress_state == "end":
                                    break

                        # If we didn't find a new out_time but the file exists, 
                        # it might mean ffmpeg is still processing
                        if not progress_updated and lines:
                            # Try to parse any speed information
                            for line in lines:
                                if line.startswith("speed="):
                                    speed = line.split("=")[1].strip()
                                    if speed and speed != "0x":
                                        job.speed = speed
                                        break

                time.sleep(1)
            except Exception as e:
                logger.warning("Error reading progress file for job %s: %s", job.id, e)
                break

    threading.Thread(target=update_progress, daemon=True).start()


async def run_job(job: Job, settings: Settings) -> None:
    if job.state == JobState.CANCELLED:
        logger.info("Skipping cancelled job %s before start", job.id)
        return

    logger.info("Starting job %s: %s", job.id, job.item_name)

    client = JellyfinClient(settings)
    job.start()

    try:
        pb_info = await client.get_playback_info(job.item_id)
        sources = pb_info.get("MediaSources", [])
        if not sources:
            logger.warning("Job %s has no playable media sources", job.id)
            job.fail("No playable media found. This may be a Season or unwatched item.")
            return

        source_id = sources[0].get("Id")
        logger.debug("Job %s using media source %s", job.id, source_id)
        output_path = (
            settings.transcoding_temp_dir
            / f"{_safe_output_name(job.item_name)}_{uuid.uuid4().hex[:8]}.mp4"
        )
        progress_path = (
            settings.transcoding_temp_dir
            / f"{_safe_output_name(job.item_name)}_{job.id[:8]}_progress.log"
        )
        job.output_path = output_path

        cmd = get_ffmpeg_command(
            settings,
            _build_transcode_url(settings, job, source_id),
            str(output_path),
            str(progress_path),
        )
        logger.debug(
            "Job %s launching ffmpeg output=%s progress=%s",
            job.id,
            output_path,
            progress_path,
        )
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        job.process = process

        # Start progress monitoring
        _read_progress_from_file(progress_path, job)

        loop = asyncio.get_event_loop()
        returncode = await loop.run_in_executor(
            None, lambda: process.wait(timeout=3600)
        )

        if job.state == JobState.CANCELLED:
            logger.info("Job %s was cancelled during processing", job.id)
            return

        if returncode != 0:
            logger.error("Job %s failed with code %s", job.id, returncode)
            job.fail(f"FFmpeg failed: {returncode}")
            return

        final_path = settings.output_dir / output_path.name
        logger.debug("Job %s moving output to %s", job.id, final_path)
        shutil.move(str(output_path), str(final_path))
        job.complete(final_path)
        logger.info("Job %s completed: %s", job.id, final_path.name)
    except Exception as exc:
        logger.exception("Job %s failed: %s", job.id, exc)
        job.fail(str(exc))
