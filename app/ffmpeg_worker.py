from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any

from app.config import load_settings
from app.jobs import JOB_QUEUE_KEY, JobState, RedisJobStore, utcnow_iso
import redis
from app.transcode import get_ffmpeg_command

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


def _run_job(store: RedisJobStore, settings, job_data: dict[str, Any]) -> None:
    job_id = job_data["job_id"]
    job = store.get(job_id)
    if not job:
        logger.warning("Skipping missing job %s", job_id)
        return

    output_path = Path(job_data["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if job.state == JobState.CANCELLED or job.cancel_requested:
        logger.info("Skipping cancelled queued job %s", job_id)
        _mark_cancelled(store, job_id, output_path)
        return

    log_path = output_path.with_suffix(".log")
    ffmpeg_args = get_ffmpeg_command(
        settings,
        input_url=job_data["input_url"],
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

    client = redis.Redis(host=settings.redis_host, port=settings.redis_port, decode_responses=True)
    client.ping()
    store = RedisJobStore(client)

    logger.info(
        "Starting ffmpeg worker with Redis at %s:%s",
        settings.redis_host,
        settings.redis_port,
    )
    while True:
        job_data: dict[str, Any] | None = None
        _, payload = client.blpop(JOB_QUEUE_KEY, timeout=0)
        try:
            job_data = json.loads(payload)
            _run_job(store, settings, job_data)
        except Exception as exc:
            logger.exception("Worker failed to process payload: %s", exc)
            job_id = None
            if isinstance(job_data, dict):
                job_id = job_data.get("job_id")
            if job_id:
                _mark_failed(store, job_id, str(exc))


if __name__ == "__main__":
    main()
