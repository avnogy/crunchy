from __future__ import annotations

import asyncio
import logging
import shutil
import os
from pathlib import Path

import redis.asyncio

from app.config import Settings, load_settings
from app.jobs import (
    JOB_QUEUE_KEY,
    Job,
    JobState,
    JobStore,
    Progress,
    get_redis_client,
    utcnow_iso,
)
from app.paths import TRANSCODING_TEMP_DIR
from app.transcode import build_output_path, get_ffmpeg_command

logger = logging.getLogger(__name__)

CANCEL_CHECK_INTERVAL = 2.0


async def _read_ffmpeg_streams(
    store: JobStore,
    job_id: str,
    process: asyncio.subprocess.Process,
    log_path: Path,
    progress_file: Path,
    temp_output_path: Path,
) -> int:
    cancel_requested = asyncio.Event()

    async def _cancel_watcher() -> None:
        while not cancel_requested.is_set():
            try:
                current_job = await store.get(job_id)
                if current_job and current_job.cancel_requested:
                    cancel_requested.set()
                    if process.returncode is None:
                        process.terminate()
                    break
            except Exception:
                pass
            await asyncio.sleep(CANCEL_CHECK_INTERVAL)

    async def _progress_reader() -> None:
        processed_lines = 0
        while True:
            if process.returncode is not None:
                break
            cur_job = await store.get(job_id)
            if not cur_job or cur_job.state != JobState.RUNNING:
                break

            if not progress_file.exists():
                await asyncio.sleep(0.5)
                continue

            lines = progress_file.read_text().splitlines()
            new_lines = lines[processed_lines:]
            processed_lines = len(lines)

            progress_updates: dict[str, object] = {}
            speed_update: str | None = None

            for line in new_lines:
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)

                if key == "out_time_us":
                    try:
                        progress_updates["current_seconds"] = int(val) / 1_000_000
                    except ValueError:
                        pass
                elif key == "fps":
                    progress_updates["fps"] = val
                elif key == "speed":
                    speed_update = val

            updates: dict[str, object] = {}
            if progress_updates:
                existing = cur_job.progress if cur_job else Progress()
                merged = existing.model_copy(update=progress_updates)
                updates["progress"] = merged
            if speed_update is not None:
                updates["speed"] = speed_update

            if updates:
                await store.update(job_id, **updates)

            await asyncio.sleep(0.5)

    async with asyncio.TaskGroup() as tg:
        cancel_task = tg.create_task(_cancel_watcher())
        progress_task = tg.create_task(_progress_reader())

        await process.wait()

        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass
        await progress_task
    if cancel_requested.is_set():
        logger.info("Cancelling running job %s", job_id)
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        progress_file.unlink(missing_ok=True)
        temp_output_path.unlink(missing_ok=True)
        await store.update(
            job_id,
            state=JobState.CANCELLED,
            finished_at=utcnow_iso(),
        )

    return_code = process.returncode or 0
    return return_code


async def _mark_failed(store: JobStore, job_id: str, message: str) -> None:
    await store.update(
        job_id,
        state=JobState.FAILED,
        error_message=message,
        finished_at=utcnow_iso(),
    )


async def _mark_cancelled(store: JobStore, job_id: str, temp_output_path: Path) -> None:
    temp_output_path.unlink(missing_ok=True)
    await store.update(
        job_id,
        state=JobState.CANCELLED,
        finished_at=utcnow_iso(),
    )


async def _run_job(store: JobStore, settings: Settings, job: Job) -> None:
    job_id = job.id
    output_path = build_output_path(job)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing = await store.find_reusable_by_item_and_preset(job.item_id, job.preset)
    if (
        existing
        and existing.state == JobState.COMPLETED
        and existing.is_download_available()
    ):
        logger.info("Reusing completed job %s for item %s", existing.id, job.item_name)
        await store.update(
            job_id,
            state=JobState.COMPLETED,
            output_path=existing.output_path,
            finished_at=existing.finished_at,
        )
        return

    log_path = TRANSCODING_TEMP_DIR / f"{job_id}.log"
    TRANSCODING_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    temp_output_path = TRANSCODING_TEMP_DIR / f"{job_id}{output_path.suffix}"

    if job.state == JobState.CANCELLED or job.cancel_requested:
        logger.info("Skipping cancelled queued job %s", job_id)
        await _mark_cancelled(store, job_id, temp_output_path)
        return
    logger.info("Running job %s -> %s (temp)", job_id, temp_output_path)

    current_job = await store.get(job_id)
    existing_progress = current_job.progress if current_job else Progress()
    await store.update(
        job_id,
        state=JobState.RUNNING,
        started_at=utcnow_iso(),
        finished_at=None,
        output_path=None,
        log_path=str(log_path),
        error_message=None,
        speed="",
        progress=existing_progress,
    )

    progress_file = TRANSCODING_TEMP_DIR / f"{job_id}.progress"
    env = os.environ.copy()
    env["FFREPORT"] = f"file={log_path}"
    ffmpeg_args = get_ffmpeg_command(
        settings,
        input_url=job.input_url,
        output_path=str(temp_output_path),
        progress_file=str(progress_file),
    )

    try:
        process = await asyncio.create_subprocess_exec(
            *ffmpeg_args,
            stdout=asyncio.subprocess.DEVNULL,
            env=env,
        )
    except FileNotFoundError as e:
        logger.error("ffmpeg not found: %s", e)
        await _mark_failed(store, job_id, f"ffmpeg not found: {e}")
        return
    except OSError as e:
        logger.error("Failed to start ffmpeg: %s", e)
        await _mark_failed(store, job_id, f"Failed to start ffmpeg: {e}")
        return

    return_code = await _read_ffmpeg_streams(
        store, job_id, process, log_path, progress_file, temp_output_path
    )

    current_job = await store.get(job_id)
    if current_job and current_job.cancel_requested:
        await _mark_cancelled(store, job_id, temp_output_path)
        return

    if return_code == 0 and (temp_output_path.exists() or output_path.exists()):

        if temp_output_path.exists():
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temp_output_path), str(output_path))
        logger.debug("Marking job %s COMPLETED (rc=%s)", job_id, return_code)
        try:
            await store.update(
                job_id,
                state=JobState.COMPLETED,
                finished_at=utcnow_iso(),
                output_path=str(output_path),
            )
        except Exception as e:
            logger.exception("Failed to set COMPLETED state for %s: %s", job_id, e)
            await _mark_failed(
                store, job_id, f"Completed file present but DB update failed: {e}"
            )
            return
        logger.info("Completed job %s", job_id)
        return

    temp_output_path.unlink(missing_ok=True)
    error_message = f"ffmpeg exited with code {return_code}"
    await _mark_failed(store, job_id, error_message)
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


async def main() -> None:
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
            await client.ping()
            store = JobStore(client)
            logger.info(
                "Connected to Redis at %s:%s", settings.redis_host, settings.redis_port
            )

            while True:
                try:
                    result = await client.blpop(JOB_QUEUE_KEY, timeout=0)
                    if result is None:
                        continue
                    _, payload = result
                    settings = _load_worker_settings(settings)
                    job = Job.model_validate_json(payload)
                    await _run_job(store, settings, job)
                except redis.asyncio.ConnectionError:
                    logger.warning("Lost connection to Redis, reconnecting...")
                    await client.close()
                    break
                except Exception as exc:
                    logger.exception("Worker failed to process job: %s", exc)

        except redis.asyncio.ConnectionError as exc:
            logger.warning(
                "Could not connect to Redis at %s:%s: %s",
                settings.redis_host,
                settings.redis_port,
                exc,
            )
            logger.info("Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as exc:
            logger.exception("Unexpected error in worker: %s", exc)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
