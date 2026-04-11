from __future__ import annotations

import asyncio
import logging
import re
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

logger = logging.getLogger(__name__)


def _safe_output_name(name: str) -> str:
    sanitized = sanitize_filename(name, replacement_text="_").strip("._")
    return sanitized or "job"


def get_ffmpeg_command(
    settings: Settings, input_url: str = "URL", output_path: str = "output.mp4"
) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "info",
        "-i",
        input_url,
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        *settings.ffmpeg_flags,
        "-progress",
        "pipe:1",
        "-stats_period",
        "2",
        output_path,
    ]


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
    if job.log_path and job.log_path.exists():
        logger.debug("Removing log for job %s at %s", job.id, job.log_path)
        job.log_path.unlink()


def _build_transcode_url(settings: Settings, job: Job, source_id: str) -> str:
    url = f"{settings.jellyfin_api_url}/Videos/{job.item_id}/master.m3u8"
    params = {
        "api_key": settings.jellyfin_api_key,
        "playSessionId": str(uuid.uuid4()),
        "mediaSourceId": source_id,
        "videoCodec": "h264",
        "audioCodec": "aac",
        "videoBitrate": str(job.preset.get("videoBitrate", 0)),
        "audioBitrate": str(job.preset.get("audioBitrate", 0)),
        "maxHeight": str(job.preset.get("maxHeight", 0)),
        "segmentContainer": "ts",
        "transcodeReasons": "ContainerNotSupported",
    }
    return f"{url}?{urlencode(params)}"


def _attach_progress_logger(
    process: subprocess.Popen[bytes], log_path: Path, job: Job
) -> None:
    speed_re = re.compile(r"speed=\s*([\d.]+)\s*x")
    dur_re = re.compile(r"Duration:\s*(\d{2}):(\d{2}):(\d{2})\.(\d{2})")

    def write_log() -> None:
        with open(log_path, "w") as f:
            for line in iter(process.stdout.readline, b""):
                decoded = line.decode("utf-8", errors="replace")

                if "progress=continue" in decoded:
                    continue

                if "Duration:" in decoded:
                    match = dur_re.search(decoded)
                    if match:
                        h, m, s, ms = map(int, match.groups())
                        job.progress["duration"] = h * 3600 + m * 60 + s + ms / 100

                if "speed=" in decoded:
                    match = speed_re.search(decoded)
                    if match:
                        job.speed = match.group(1) + "x"

                if decoded.startswith("out_time="):
                    parts = decoded.strip().split("=")
                    if len(parts) == 2:
                        job.progress["current"] = parts[1]

                f.write(decoded)
                f.flush()

    threading.Thread(target=write_log, daemon=True).start()


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
        log_path = (
            settings.transcoding_temp_dir
            / f"{_safe_output_name(job.item_name)}_{job.id[:8]}.log"
        )
        job.output_path = output_path
        job.log_path = log_path

        cmd = get_ffmpeg_command(
            settings, _build_transcode_url(settings, job, source_id), str(output_path)
        )
        logger.debug(
            "Job %s launching ffmpeg output=%s log=%s", job.id, output_path, log_path
        )
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        job.process = process
        _attach_progress_logger(process, log_path, job)

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
        shutil.move(str(log_path), str(settings.output_dir / log_path.name))
        job.log_path = settings.output_dir / log_path.name
        job.complete(final_path)
        logger.info("Job %s completed: %s", job.id, final_path.name)
    except Exception as exc:
        logger.exception("Job %s failed: %s", job.id, exc)
        job.fail(str(exc))
