from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import redis.asyncio

from app.config import Settings, load_settings
from app.jobs import JOB_QUEUE_KEY, Job, JobState, JobStore, Progress, get_redis_client, utcnow_iso
from app.paths import TRANSCODING_TEMP_DIR
from app.transcode import build_output_path, get_ffmpeg_command

logger = logging.getLogger(__name__)

CANCEL_CHECK_INTERVAL = 2
PROGRESS_UPDATE_INTERVAL = 2


async def _check_cancel_task(store: JobStore, job_id: str, cancel_requested: asyncio.Event) -> None:
    while not cancel_requested.is_set():
        try:
            current_job = await store.get(job_id)
            if current_job and current_job.cancel_requested:
                cancel_requested.set()
                break
        except Exception:
            pass
        await asyncio.sleep(CANCEL_CHECK_INTERVAL)


async def _read_ffmpeg_streams(
    store: JobStore, job_id: str, process: asyncio.subprocess.Process, log_path: Path
) -> int:
    progress_buffer: dict[str, str] = {}
    buffer_lock = asyncio.Lock()
    cancel_requested = asyncio.Event()
    last_progress_update = 0.0
    final_progress_sent = False
    log_file = log_path.open("ab")

    cancel_task = asyncio.create_task(_check_cancel_task(store, job_id, cancel_requested))

    async def read_stream(stream: asyncio.StreamReader, is_stderr: bool) -> None:
        nonlocal progress_buffer, last_progress_update, final_progress_sent
        while True:
            line = await stream.readline()
            if not line:
                if not is_stderr:
                    async with buffer_lock:
                        progress_buffer.clear()
                break

            if is_stderr:
                log_file.write(line)
                log_file.flush()
                continue

            decoded = line.decode("utf-8", errors="replace")
            entry = decoded.strip()
            if not entry or "=" not in entry:
                continue

            key_name, value = entry.split("=", 1)

            async with buffer_lock:
                progress_buffer[key_name] = value

                if key_name != "progress":
                    continue

                progress_payload = Progress()
                out_time_us = progress_buffer.get("out_time_us")
                if out_time_us:
                    try:
                        progress_payload.current_seconds = int(out_time_us) / 1_000_000
                    except ValueError:
                        pass

                fps_value = progress_buffer.get("fps")
                frame_value = progress_buffer.get("frame")
                if fps_value is not None:
                    progress_payload.fps = fps_value
                if frame_value is not None:
                    progress_payload.frame = frame_value

                speed = progress_buffer.get("speed")
                progress_buffer.clear()

            current_time = asyncio.get_running_loop().time()
            if current_time - last_progress_update >= PROGRESS_UPDATE_INTERVAL:
                current_job = await store.get(job_id)
                existing_progress = current_job.progress if current_job else Progress()
                update_data = progress_payload.model_dump(exclude_none=True)
                merged = existing_progress.model_copy(update=update_data)

                changes: dict[str, object] = {"progress": merged}
                if speed:
                    changes["speed"] = speed
                await store.update(job_id, **changes)
                last_progress_update = current_time
                final_progress_sent = True

    try:
        stdout_task = asyncio.create_task(
            read_stream(process.stdout, is_stderr=False)
        )
        stderr_task = asyncio.create_task(
            read_stream(process.stderr, is_stderr=True)
        )

        done, pending = await asyncio.wait(
            [stdout_task, stderr_task, cancel_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            try:
                await task
            except Exception:
                pass

        if cancel_requested.is_set():
            logger.info("Cancelling running job %s", job_id)
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

        if not final_progress_sent:
            current_job = await store.get(job_id)
            existing_progress = current_job.progress if current_job else Progress()
            changes = {"progress": existing_progress}
            if speed := progress_buffer.get("speed"):
                changes["speed"] = speed
            await store.update(job_id, **changes)

    except Exception as e:
        logger.exception("Error in ffmpeg streams for job %s: %s", job_id, e)
    finally:
        log_file.close()

    return_code = await process.wait()
    return return_code


async def _mark_failed(store: JobStore, job_id: str, message: str) -> None:
    await store.update(
        job_id,
        state=JobState.FAILED,
        error_message=message,
        finished_at=utcnow_iso(),
    )


async def _mark_cancelled(store: JobStore, job_id: str, output_path: Path) -> None:
    output_path.unlink(missing_ok=True)
    await store.update(
        job_id,
        state=JobState.CANCELLED,
        finished_at=utcnow_iso(),
        output_path=None,
    )


async def _run_job(store: JobStore, settings: Settings, job: Job) -> None:
    job_id = job.id
    output_path = build_output_path(job)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing = await store.find_reusable_by_item_and_preset(job.item_id, job.preset)
    if existing and existing.state == JobState.COMPLETED and existing.is_download_available():
        logger.info("Reusing completed job %s for item %s", existing.id, job.item_name)
        await store.update(
            job_id,
            state=JobState.COMPLETED,
            output_path=existing.output_path,
            finished_at=existing.finished_at,
        )
        return

    if job.state == JobState.CANCELLED or job.cancel_requested:
        logger.info("Skipping cancelled queued job %s", job_id)
        await _mark_cancelled(store, job_id, output_path)
        return

    log_path = output_path.with_suffix(".log")
    ffmpeg_args = get_ffmpeg_command(
        settings,
        input_url=job.input_url or "",
        output_path=str(output_path),
        preset=job.preset,
    )
    logger.info("Running job %s -> %s", job_id, output_path)

    await store.update(
        job_id,
        state=JobState.RUNNING,
        started_at=utcnow_iso(),
        finished_at=None,
        output_path=None,
        log_path=str(log_path),
        error_message=None,
        speed="",
        progress=Progress(),
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

    try:
        process = await asyncio.create_subprocess_exec(
            *ffmpeg_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        logger.error("ffmpeg not found: %s", e)
        await _mark_failed(store, job_id, f"ffmpeg not found: {e}")
        return
    except OSError as e:
        logger.error("Failed to start ffmpeg: %s", e)
        await _mark_failed(store, job_id, f"Failed to start ffmpeg: {e}")
        return

    return_code = await _read_ffmpeg_streams(store, job_id, process, log_path)

    current_job = await store.get(job_id)
    if current_job and current_job.cancel_requested:
        await _mark_cancelled(store, job_id, output_path)
        return

    if return_code == 0 and output_path.exists():
        await store.update(
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
            logger.info("Connected to Redis at %s:%s", settings.redis_host, settings.redis_port)

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