from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import redis.asyncio
from redis.exceptions import WatchError
from pydantic import BaseModel, Field, computed_field

JOB_QUEUE_KEY = "jobs:queue"
JOB_IDS_KEY = "jobs:ids"


def get_redis_client(settings) -> redis.asyncio.Redis:
    return redis.asyncio.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        decode_responses=True,
        socket_connect_timeout=5,
    )


class JobState(str, Enum):
    model_config = {"extra": "forbid"}
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Progress(BaseModel):
    model_config = {"extra": "allow"}
    duration: Optional[float] = None
    current_seconds: Optional[float] = None
    fps: Optional[str] = None
    frame: Optional[str] = None


class Job(BaseModel):
    model_config = {"extra": "forbid"}
    id: str
    item_id: str
    item_name: str
    preset: dict[str, Any]
    state: JobState = JobState.QUEUED
    created_at: str = Field(default_factory=utcnow_iso)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    output_path: Optional[str] = None
    log_path: Optional[str] = None
    input_url: Optional[str] = None
    error_message: Optional[str] = None
    speed: str = ""
    audio_stream_index: int | None = None
    subtitle_stream_index: int | None = None
    progress: Progress = Field(default_factory=Progress)
    cancel_requested: bool = False

    @computed_field
    @property
    def download_available(self) -> bool:
        return self.is_download_available()

    def is_download_available(self) -> bool:
        return bool(self.output_path and Path(self.output_path).exists())


class DuplicateJobError(Exception):
    def __init__(self, job: Job) -> None:
        self.job = job
        super().__init__(f"Duplicate job already exists: {job.id}")


def job_dedupe_id(
    item_id: str,
    preset_key: str,
    audio_stream_index: int | None = None,
    subtitle_stream_index: int | None = None,
) -> str:
    identity = {
        "audio_stream_index": audio_stream_index,
        "item_id": item_id,
        "preset": preset_key,
        "subtitle_stream_index": subtitle_stream_index,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"dedupe-{digest[:32]}"


def new_job(
    item_id: str,
    item_name: str,
    preset_key: str,
    preset: dict[str, Any],
    audio_stream_index: int | None = None,
    subtitle_stream_index: int | None = None,
) -> Job:
    return Job(
        id=job_dedupe_id(
            item_id,
            preset_key,
            audio_stream_index,
            subtitle_stream_index,
        ),
        item_id=item_id,
        item_name=item_name,
        preset=preset,
        audio_stream_index=audio_stream_index,
        subtitle_stream_index=subtitle_stream_index,
    )


class JobStore:
    def __init__(self, client: redis.asyncio.Redis) -> None:
        self.client = client

    async def add_pending(self, job: Job) -> Job:
        key = f"job:{job.id}"
        job_json = job.model_dump_json(exclude_computed_fields=True)

        while True:
            pipe = self.client.pipeline()
            try:
                await pipe.watch(key)
                existing_data = await pipe.get(key)
                if existing_data:
                    existing_job = self._parse_job(existing_data)
                    if existing_job and not self._can_replace(existing_job):
                        raise DuplicateJobError(existing_job)

                pipe.multi()
                pipe.set(key, job_json)
                pipe.lrem(JOB_QUEUE_KEY, 0, job.id)
                pipe.lrem(JOB_IDS_KEY, 0, job.id)
                pipe.lpush(JOB_IDS_KEY, job.id)
                await pipe.execute()
                return job
            except WatchError:
                continue
            finally:
                await pipe.reset()

    @staticmethod
    def _parse_job(data: str) -> Job | None:
        try:
            return Job.model_validate_json(data)
        except ValueError:
            return None

    @staticmethod
    def _can_replace(job: Job) -> bool:
        if job.state in (JobState.QUEUED, JobState.RUNNING):
            return False
        if job.state == JobState.COMPLETED:
            return not job.is_download_available()
        return True

    async def get(self, job_id: str) -> Job | None:
        data = await self.client.get(f"job:{job_id}")
        return Job.model_validate_json(data) if data else None

    async def list(self) -> list[Job]:
        job_ids = await self.client.lrange(JOB_IDS_KEY, 0, -1)
        if not job_ids:
            return []
        keys = [f"job:{jid}" for jid in job_ids]
        values = await self.client.mget(keys)
        return [Job.model_validate_json(v) for v in values if v]

    async def update(self, job_id: str, **changes: Any) -> Job | None:
        key = f"job:{job_id}"

        data = await self.client.get(key)
        if not data:
            return None

        job = Job.model_validate_json(data)
        updated = job.model_copy(update=changes)

        await self.client.set(
            key, updated.model_dump_json(exclude_computed_fields=True)
        )

        return updated

    async def enqueue_existing(self, job: Job) -> None:
        await self.client.rpush(JOB_QUEUE_KEY, job.id)

    async def delete_if_unchanged(self, job: Job) -> Job | None:
        key = f"job:{job.id}"
        job_json = job.model_dump_json(exclude_computed_fields=True)

        while True:
            pipe = self.client.pipeline()
            try:
                await pipe.watch(key)
                data = await pipe.get(key)
                if data != job_json:
                    return None

                pipe.multi()
                pipe.delete(key)
                pipe.lrem(JOB_IDS_KEY, 0, job.id)
                await pipe.execute()
                return job
            except WatchError:
                continue
            finally:
                await pipe.reset()

    async def delete(self, job_id: str) -> Job | None:
        key = f"job:{job_id}"
        data = await self.client.get(key)
        if not data:
            return None

        job = Job.model_validate_json(data)

        pipe = self.client.pipeline()
        pipe.delete(key)
        pipe.lrem(JOB_IDS_KEY, 0, job_id)
        await pipe.execute()
        return job
