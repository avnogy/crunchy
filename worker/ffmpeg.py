from __future__ import annotations

import logging
import selectors
import subprocess
import time
from pathlib import Path

import redis

from app.config import Settings, load_settings
from app.jobs import JOB_QUEUE_KEY, Job, JobState, RedisJobStore, get_redis_client, utcnow_iso
from app.paths import TRANSCODING_TEMP_DIR
from app.transcode import build_output_path, get_ffmpeg_command

logger = logging.getLogger(__name__)

def _read_ffmpeg_streams(
    store: RedisJobStore, job_id: str, process: subprocess.Popen, log_path: Path
) -> int:
    selector = selectors.DefaultSelector()
    progress_buffer: dict[str, str] = {}

    assert process.stdout is not None
    assert process.stderr is not None
    selector.register(process.stdout, selectors.EVENT_READ, data="stdout")
    selector.register(process.stderr, selectors.EVENT_READ, data="stderr")

    with log_path.open("ab") as log_file:
        while selector.get_map():
            current_job = store.get(job_id)
            if current_job and current_job.cancel_requested:
                logger.info("Cancelling running job %s", job_id)
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                break

            events = selector.select(timeout=1)
            if not events:
                if process.poll() is not None:
                    break
                continue

            for key, _ in events:
                stream = key.fileobj
                line = stream.readline()
                if not line:
                    try:
                        selector.unregister(stream)
                    except Exception:
                        pass
                    continue

                decoded = line.decode("utf-8", errors="replace")
                if key.data == "stderr":
                    log_file.write(line)
                    log_file.flush()
                    continue

                entry = decoded.strip()
                if not entry or "=" not in entry:
                    continue
                key_name, value = entry.split("=", 1)
                progress_buffer[key_name] = value

                if key_name != "progress":
                    continue

                progress_payload: dict[str, object] = {}
                out_time_us = progress_buffer.get("out_time_us")
                if out_time_us:
                    try:
                        progress_payload["current_seconds"] = int(out_time_us) / 1_000_000
                    except ValueError:
                        pass
                if fps := progress_buffer.get("fps"):
                    progress_payload["fps"] = fps
                if frame := progress_buffer.get("frame"):
                    progress_payload["frame"] = frame

                current_job = store.get(job_id)
                existing_progress = (
                    dict(current_job.progress)
                    if current_job and isinstance(current_job.progress, dict)
                    else {}
                )
                existing_progress.update(progress_payload)

                changes: dict[str, object] = {"progress": existing_progress}
                if speed := progress_buffer.get("speed"):
                    changes["speed"] = speed
                store.update(job_id, **changes)
                progress_buffer = {}

    return process.wait()


def _mark_failed(store: RedisJobStore, job_id: str, message: str) -> None:
    store.update(
        job_id,
        state=JobState.FAILED,
        error_message=message,
        finished_at=utcnow_iso(),
    )


def _mark_cancelled(store: RedisJobStore, job_id: str, output_path: Path) -> None:
    output_path.unlink(missing_ok=True)
    store.update(
        job_id,
        state=JobState.CANCELLED,
        cancel_requested=True,
        finished_at=utcnow_iso(),
        output_path=None,
    )


def _run_job(store: RedisJobStore, settings: Settings, job: Job) -> None:
    job_id = job.id
    output_path = build_output_path(job)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing = store.find_reusable_by_item_and_preset(job.item_id, job.preset)
    if existing and existing.state == JobState.COMPLETED and existing.is_download_available():
        logger.info("Reusing completed job %s for item %s", existing.id, job.item_name)
        store.update(
            job_id,
            state=JobState.COMPLETED,
            output_path=existing.output_path,
            finished_at=existing.finished_at,
        )
        return

    if job.state == JobState.CANCELLED or job.cancel_requested:
        logger.info("Skipping cancelled queued job %s", job_id)
        _mark_cancelled(store, job_id, output_path)
        return

    log_path = output_path.with_suffix(".log")
    ffmpeg_args = get_ffmpeg_command(
        settings,
        input_url=job.input_url or "",
        output_path=str(output_path),
        preset=job.preset,
    )
    logger.info("Running job %s -> %s", job_id, output_path)

    store.update(
        job_id,
        state=JobState.RUNNING,
        started_at=utcnow_iso(),
        finished_at=None,
        output_path=None,
        log_path=str(log_path),
        error_message=None,
        speed="",
        progress={},
    )

    ffmpeg_args = [
        ffmpeg_args[0],
        "-progress",
        "pipe:1",
        "-nostats",
        "-stats_period",
        "2",
        *ffmpeg_args[1:],
    ]

    process = subprocess.Popen(
        ffmpeg_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return_code = _read_ffmpeg_streams(store, job_id, process, log_path)

    current_job = store.get(job_id)
    if current_job and current_job.cancel_requested:
        _mark_cancelled(store, job_id, output_path)
        return

    if return_code == 0 and output_path.exists():
        store.update(
            job_id,
            state=JobState.COMPLETED,
            finished_at=utcnow_iso(),
            output_path=str(output_path),
            error_message=None,
        )
        logger.info("Completed job %s", job_id)
        return

    output_path.unlink(missing_ok=True)
    error_message = f"ffmpeg exited with code {return_code}"
    _mark_failed(store, job_id, error_message)
    logger.error("Job %s failed: %s", job_id, error_message)


def _load_worker_settings(previous: Settings | None = None) -> Settings:
    settings = load_settings()
    if previous is None:
        return settings

    if settings.model_dump() != previous.model_dump():
        logger.info(
            "Reloaded worker settings redis=%s:%s log_level=%s",
            settings.redis_host,
            settings.redis_port,
            settings.log_level,
        )
        logging.getLogger().setLevel(settings.log_level)

    return settings


def main() -> None:
    settings = _load_worker_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info(
        "Starting ffmpeg worker, Redis at %s:%s worker_temp_dir=%s",
        settings.redis_host,
        settings.redis_port,
        TRANSCODING_TEMP_DIR,
    )

    while True:
        try:
            settings = _load_worker_settings(settings)
            client = get_redis_client(settings)
            client.ping()
            store = RedisJobStore(client)
            logger.info("Connected to Redis at %s:%s", settings.redis_host, settings.redis_port)

            while True:
                try:
                    _, payload = client.blpop(JOB_QUEUE_KEY, timeout=0)
                    settings = _load_worker_settings(settings)
                    job = Job.model_validate_json(payload)
                    _run_job(store, settings, job)
                except redis.ConnectionError:
                    logger.warning("Lost connection to Redis, reconnecting...")
                    break
                except Exception as exc:
                    logger.exception("Worker failed to process job: %s", exc)

        except redis.ConnectionError as exc:
            logger.warning(
                "Could not connect to Redis at %s:%s: %s",
                settings.redis_host,
                settings.redis_port,
                exc,
            )
            logger.info("Retrying in 5 seconds...")
            time.sleep(5)
        except Exception as exc:
            logger.exception("Unexpected error in worker: %s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
