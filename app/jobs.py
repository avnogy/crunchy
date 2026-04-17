from pydantic import BaseModel, Field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import json
import uuid
import redis

JOB_QUEUE_KEY = "jobs:queue"
JOB_IDS_KEY = "jobs:ids"


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
    error_message: Optional[str] = None
    speed: str = ""
    progress: dict[str, Any] = {}
    cancel_requested: bool = False

    @property
    def preset_signature(self) -> str:
        return json.dumps(self.preset, sort_keys=True, separators=(",", ":"))

    def is_download_available(self) -> bool:
        return bool(self.output_path and Path(self.output_path).exists())


def new_job(item_id: str, item_name: str, preset: dict[str, Any]) -> Job:
    return Job(
        item_id=item_id,
        item_name=item_name,
        preset=preset,
    )


class RedisJobStore:
    def __init__(self, client: redis.Redis) -> None:
        self.client = client

    def add(self, job: Job, payload: dict[str, Any]) -> Job:
        pipe = self.client.pipeline()
        pipe.set(f"job:{job.id}", job.model_dump_json())
        pipe.lpush(JOB_IDS_KEY, job.id)
        pipe.rpush(JOB_QUEUE_KEY, json.dumps(payload))
        pipe.execute()
        return job

    def get(self, job_id: str) -> Job | None:
        data = self.client.get(f"job:{job_id}")
        return Job.model_validate_json(data) if data else None

    def list(self) -> list[Job]:
        return [job for job in (self.get(jid) for jid in self.client.lrange(JOB_IDS_KEY, 0, -1)) if job]

    def find_reusable_by_item_and_preset(
        self, item_id: str, preset: dict[str, Any]
    ) -> Job | None:
        signature = json.dumps(preset, sort_keys=True, separators=(",", ":"))
        for job in self.list():
            if job.item_id != item_id:
                continue
            if job.preset_signature != signature:
                continue
            if job.state in (JobState.QUEUED, JobState.RUNNING):
                return job
            if job.state == JobState.COMPLETED and job.is_download_available():
                return job
        return None

    def update(self, job_id: str, **changes: Any) -> Job | None:
        key = f"job:{job_id}"

        data = self.client.get(key)
        if not data:
            return None

        job = Job.model_validate_json(data)
        updated = job.model_copy(update=changes)

        self.client.set(key, updated.model_dump_json())

        return updated
