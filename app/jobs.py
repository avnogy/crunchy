import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import redis.asyncio
from pydantic import BaseModel, Field, computed_field

JOB_QUEUE_KEY = "jobs:queue"
JOB_IDS_KEY = "jobs:ids"


def get_redis_client(settings) -> redis.asyncio.Redis:
    return redis.asyncio.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
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


class Job(BaseModel):
    model_config = {"extra": "forbid"}
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
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
    progress: dict[str, Any] = Field(default_factory=dict)
    cancel_requested: bool = False

    @property
    def preset_signature(self) -> str:
        return json.dumps(self.preset, sort_keys=True, separators=(",", ":"))

    @computed_field
    @property
    def download_available(self) -> bool:
        return self.is_download_available()

    def is_download_available(self) -> bool:
        return bool(self.output_path and Path(self.output_path).exists())


def new_job(item_id: str, item_name: str, preset: dict[str, Any]) -> Job:
    return Job(
        item_id=item_id,
        item_name=item_name,
        preset=preset,
    )


class JobStore:
    def __init__(self, client: redis.asyncio.Redis) -> None:
        self.client = client

    async def add(self, job: Job) -> Job:
        pipe = self.client.pipeline()
        serialized = job.model_dump_json(exclude_computed_fields=True)
        pipe.set(f"job:{job.id}", serialized)
        pipe.lpush(JOB_IDS_KEY, job.id)
        pipe.rpush(JOB_QUEUE_KEY, serialized)
        await pipe.execute()
        return job

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

    async def find_reusable_by_item_and_preset(
        self, item_id: str, preset: dict[str, Any]
    ) -> Job | None:
        signature = json.dumps(preset, sort_keys=True, separators=(",", ":"))
        for job in await self.list():
            if job.item_id != item_id:
                continue
            if job.preset_signature != signature:
                continue
            if job.state in (JobState.QUEUED, JobState.RUNNING):
                return job
            if job.state == JobState.COMPLETED and job.is_download_available():
                return job
        return None

    async def update(self, job_id: str, **changes: Any) -> Job | None:
        key = f"job:{job_id}"

        data = await self.client.get(key)
        if not data:
            return None

        job = Job.model_validate_json(data)
        updated = job.model_copy(update=changes)

        await self.client.set(key, updated.model_dump_json(exclude_computed_fields=True))

        return updated
