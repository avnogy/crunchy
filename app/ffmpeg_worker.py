from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from app.config import load_settings
from app.jobs import JOB_QUEUE_KEY, Job, JobState, RedisJobStore, utcnow_iso, get_redis_client
from app.transcode import build_output_path, get_ffmpeg_command

logger = logging.getLogger(__name__)


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


def _run_job(store: RedisJobStore, settings, job: Job) -> None:
    job_id = job.id
    output_path = build_output_path(settings, job)
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
    )

    with log_path.open("ab") as log_file:
        process = subprocess.Popen(
            ffmpeg_args,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

        cancelled = False
        while True:
            return_code = process.poll()
            if return_code is not None:
                break

            current_job = store.get(job_id)
            if current_job and current_job.cancel_requested:
                logger.info("Cancelling running job %s", job_id)
                cancelled = True
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                break

            time.sleep(1)

        if cancelled:
            _mark_cancelled(store, job_id, output_path)
            return

        if process.returncode == 0 and output_path.exists():
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
        error_message = f"ffmpeg exited with code {process.returncode}"
        _mark_failed(store, job_id, error_message)
        logger.error("Job %s failed: %s", job_id, error_message)


def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    client = get_redis_client(settings)
    client.ping()
    store = RedisJobStore(client)

    logger.info(
        "Starting ffmpeg worker with Redis at %s:%s",
        settings.redis_host,
        settings.redis_port,
    )
    while True:
        _, payload = client.blpop(JOB_QUEUE_KEY, timeout=0)
        try:
            job = Job.model_validate_json(payload)
            _run_job(store, settings, job)
        except Exception as exc:
            logger.exception("Worker failed to process job: %s", exc)


if __name__ == "__main__":
    main()
