from __future__ import annotations

import logging
from pathlib import Path
from contextlib import suppress

import redis.asyncio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api_models import CreateJobPayload
from app.jobs import (
    DuplicateJobError,
    Job,
    JobState,
    JobStore,
    get_redis_client,
    new_job,
    utcnow_iso,
)
from app.paths import MANAGED_DIRECTORIES, TRANSCODING_TEMP_DIR
from app.transcode import enqueue_job

router = APIRouter()
logger = logging.getLogger(__name__)


def get_store(settings) -> JobStore:
    return JobStore(get_redis_client(settings))


async def _get_job(store: JobStore, job_id: str) -> Job:
    job = await store.get(job_id)
    if not job:
        logger.warning("Requested missing job %s", job_id)
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/api/jobs")
async def create_job(request: Request, data: CreateJobPayload):
    settings = request.app.state.settings
    presets = settings.presets
    item_id = data.item_id
    item_name = data.item_name
    preset_key = data.preset
    job: Job | None = None
    if preset_key not in presets:
        logger.warning(
            "Rejected invalid job creation request item_id=%s preset=%s",
            item_id,
            preset_key,
        )
        raise HTTPException(status_code=400, detail="Invalid request")

    preset = presets[preset_key]
    try:
        store = get_store(settings)
        job = new_job(
            item_id=item_id,
            item_name=item_name,
            preset_key=preset_key,
            preset=preset,
            audio_stream_index=data.audio_stream_index,
            subtitle_stream_index=data.subtitle_stream_index,
        )
        await store.add_pending(job)
        job = await enqueue_job(job, settings, store)
        await store.enqueue_existing(job)
    except DuplicateJobError as exc:
        logger.info(
            "Rejected duplicate job %s for item_id=%s preset=%s",
            exc.job.id,
            item_id,
            preset_key,
        )
        raise HTTPException(
            status_code=409,
            detail="Duplicate job already exists",
        ) from exc
    except redis.asyncio.RedisError as exc:
        if job is not None:
            with suppress(Exception):
                await get_store(settings).delete_if_unchanged(job)
        logger.exception("Redis failure while creating job for item_id=%s", item_id)
        raise HTTPException(status_code=503, detail="Job queue unavailable") from exc
    except Exception as exc:
        if job is not None:
            with suppress(Exception):
                await get_store(settings).delete_if_unchanged(job)
        logger.exception("Failed to create job for item_id=%s", item_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    logger.info("Queued new job %s for item_id=%s preset=%s", job.id, item_id, preset_key)
    return JSONResponse({"job": job.model_dump()}, status_code=201)


@router.get("/api/jobs")
async def list_jobs(request: Request):
    settings = request.app.state.settings
    try:
        jobs = [j.model_dump() for j in await get_store(settings).list()]
    except redis.asyncio.RedisError as exc:
        logger.exception("Redis failure while listing jobs")
        raise HTTPException(status_code=503, detail="Job queue unavailable") from exc
    logger.debug("Listing %d job(s)", len(jobs))
    return JSONResponse({"jobs": jobs})


@router.get("/api/jobs/{job_id}")
async def get_job(request: Request, job_id: str):
    settings = request.app.state.settings
    try:
        job = await _get_job(get_store(settings), job_id)
    except redis.asyncio.RedisError as exc:
        logger.exception("Redis failure while loading job %s", job_id)
        raise HTTPException(status_code=503, detail="Job queue unavailable") from exc
    logger.debug("Returning job %s state=%s", job_id, job.state.value)
    return JSONResponse({"job": job.model_dump()})


@router.post("/api/jobs/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str):
    settings = request.app.state.settings
    try:
        store = get_store(settings)
        job = await _get_job(store, job_id)
    except redis.asyncio.RedisError as exc:
        logger.exception("Redis failure while cancelling job %s", job_id)
        raise HTTPException(status_code=503, detail="Job queue unavailable") from exc
    if job.state not in (JobState.QUEUED, JobState.RUNNING):
        logger.warning("Rejecting cancel for job %s", job_id)
        raise HTTPException(status_code=400, detail="Cannot cancel")

    job = await store.update(
        job_id,
        state=JobState.CANCELLED,
        cancel_requested=True,
        finished_at=utcnow_iso(),
    )

    logger.info("Cancelled job %s", job_id)
    return JSONResponse({"job": job.model_dump() if job else None})


@router.delete("/api/jobs/{job_id}")
async def delete_job(request: Request, job_id: str):
    settings = request.app.state.settings
    try:
        store = get_store(settings)
        job = await _get_job(store, job_id)
    except redis.asyncio.RedisError as exc:
        logger.exception("Redis failure while deleting job %s", job_id)
        raise HTTPException(status_code=503, detail="Job queue unavailable") from exc

    if job.state in (JobState.QUEUED, JobState.RUNNING):
        logger.warning("Rejecting delete for running job %s", job_id)
        raise HTTPException(status_code=400, detail="Cannot delete an active job")

    deleted_job = await store.delete(job_id)
    if not deleted_job:
        raise HTTPException(status_code=404, detail="Job not found")

    deleted_files: list[str] = []
    for raw_path in (deleted_job.output_path, deleted_job.log_path):
        if not raw_path:
            continue
        path = Path(raw_path)
        try:
            resolved = path.resolve(strict=False)
        except OSError:
            continue

        is_managed = False
        for directory in MANAGED_DIRECTORIES:
            try:
                resolved.relative_to(directory)
                is_managed = True
                break
            except ValueError:
                continue
        if not is_managed:
            logger.warning("Skipping unmanaged job file deletion for %s", path)
            continue
        if path.exists():
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Failed to delete job file %s: %s", path, exc)
            else:
                deleted_files.append(str(path))

    for temp_path in TRANSCODING_TEMP_DIR.glob(f"{job.id}*"):
        if temp_path.is_file():
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Failed to delete temp file %s: %s", temp_path, exc)
            else:
                deleted_files.append(str(temp_path))

    logger.info("Deleted job %s and %d related file(s)", job_id, len(deleted_files))
    return JSONResponse({"deleted_job_id": job_id, "deleted_files": deleted_files})


@router.get("/api/jobs/{job_id}/download")
async def download_job(request: Request, job_id: str):
    settings = request.app.state.settings
    try:
        job = await _get_job(get_store(settings), job_id)
    except redis.asyncio.RedisError as exc:
        logger.exception("Redis failure while loading download for job %s", job_id)
        raise HTTPException(status_code=503, detail="Job queue unavailable") from exc
    if job.state != JobState.COMPLETED or not job.is_download_available():
        logger.warning("Download requested for unavailable job output job_id=%s", job_id)
        raise HTTPException(status_code=400, detail="Not ready")
    output_path = Path(job.output_path)
    logger.info("Serving download for job %s", job_id)
    return FileResponse(output_path, media_type="video/mp4", filename=output_path.name)


@router.get("/api/jobs/{job_id}/log")
async def get_job_log_api(request: Request, job_id: str):
    settings = request.app.state.settings
    try:
        job = await _get_job(get_store(settings), job_id)
    except redis.asyncio.RedisError as exc:
        logger.exception("Redis failure while loading log for job %s", job_id)
        raise HTTPException(status_code=503, detail="Job queue unavailable") from exc
    if not job.log_path or not Path(job.log_path).exists():
        logger.warning("Log requested for unavailable job %s", job_id)
        raise HTTPException(status_code=404, detail="Log not found")
    logger.info("Serving log for job %s", job_id)
    headers = {"Cache-Control": "no-store"}
    return FileResponse(job.log_path, media_type="text/plain", headers=headers)


@router.get("/jobs")
async def jobs_page(request: Request):
    templates = request.app.state.templates
    settings = request.app.state.settings
    logger.debug(
        "Rendering jobs page with poll_interval_ms=%s",
        settings.jobs_poll_interval_ms,
    )
    return templates.TemplateResponse(
        request,
        "jobs/index.html",
        {
            "active_page": "jobs",
            "jobs_poll_interval_ms": settings.jobs_poll_interval_ms,
        },
    )
