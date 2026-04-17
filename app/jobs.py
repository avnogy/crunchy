from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import redis

JOB_QUEUE_KEY = "jobs:queue"
JOB_IDS_KEY = "jobs:ids"


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def preset_signature(preset: dict[str, Any]) -> str:
    return json.dumps(preset, sort_keys=True, separators=(",", ":"))


@dataclass(slots=True)
class Job:
    id: str
    item_id: str
    item_name: str
    preset: dict[str, Any]
    state: JobState
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    output_path: str | None = None
    log_path: str | None = None
    error_message: str | None = None
    speed: str = ""
    progress: dict[str, Any] | None = None
    cancel_requested: bool = False

    def is_download_available(self) -> bool:
        return bool(self.output_path and Path(self.output_path).exists())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "item_id": self.item_id,
            "item_name": self.item_name,
            "preset": self.preset,
            "state": self.state.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "output_path": self.output_path,
            "log_path": self.log_path,
            "download_available": self.is_download_available(),
            "error_message": self.error_message,
            "speed": self.speed,
            "progress": self.progress or {},
            "cancel_requested": self.cancel_requested,
        }


def new_job(item_id: str, item_name: str, preset: dict[str, Any]) -> Job:
    return Job(
        id=str(uuid.uuid4()),
        item_id=item_id,
        item_name=item_name,
        preset=preset,
        state=JobState.QUEUED,
        created_at=utcnow_iso(),
    )


def get_redis_client(host: str, port: int) -> redis.Redis:
    return redis.Redis(host=host, port=port, decode_responses=True)


def _serialize_job(job: Job) -> dict[str, str]:
    return {
        "id": job.id,
        "item_id": job.item_id,
        "item_name": job.item_name,
        "preset": json.dumps(job.preset, sort_keys=True),
        "preset_signature": preset_signature(job.preset),
        "state": job.state.value,
        "created_at": job.created_at,
        "started_at": job.started_at or "",
        "finished_at": job.finished_at or "",
        "output_path": job.output_path or "",
        "log_path": job.log_path or "",
        "error_message": job.error_message or "",
        "speed": job.speed,
        "progress": json.dumps(job.progress or {}),
        "cancel_requested": "1" if job.cancel_requested else "0",
    }


def _deserialize_job(data: dict[str, str] | None) -> Job | None:
    if not data:
        return None

    state = data.get("state", JobState.FAILED.value)
    try:
        job_state = JobState(state)
    except ValueError:
        job_state = JobState.FAILED

    return Job(
        id=data["id"],
        item_id=data.get("item_id", ""),
        item_name=data.get("item_name", ""),
        preset=json.loads(data.get("preset", "{}")),
        state=job_state,
        created_at=data.get("created_at", ""),
        started_at=data.get("started_at") or None,
        finished_at=data.get("finished_at") or None,
        output_path=data.get("output_path") or None,
        log_path=data.get("log_path") or None,
        error_message=data.get("error_message") or None,
        speed=data.get("speed", ""),
        progress=json.loads(data.get("progress", "{}")),
        cancel_requested=data.get("cancel_requested") == "1",
    )


class RedisJobStore:
    def __init__(self, client: redis.Redis) -> None:
        self.client = client

    def add(self, job: Job, payload: dict[str, Any]) -> Job:
        pipe = self.client.pipeline()
        pipe.hset(f"job:{job.id}", mapping=_serialize_job(job))
        pipe.lpush(JOB_IDS_KEY, job.id)
        pipe.rpush(JOB_QUEUE_KEY, json.dumps(payload, sort_keys=True))
        pipe.execute()
        return job

    def get(self, job_id: str) -> Job | None:
        return _deserialize_job(self.client.hgetall(f"job:{job_id}"))

    def list(self) -> list[Job]:
        job_ids = self.client.lrange(JOB_IDS_KEY, 0, -1)
        jobs: list[Job] = []
        for current_job_id in job_ids:
            job = self.get(current_job_id)
            if job:
                jobs.append(job)
        return jobs

    def find_reusable_by_item_and_preset(
        self, item_id: str, preset: dict[str, Any]
    ) -> Job | None:
        signature = preset_signature(preset)
        for job in self.list():
            if job.item_id != item_id:
                continue
            if preset_signature(job.preset) != signature:
                continue
            if job.state in (JobState.QUEUED, JobState.RUNNING):
                return job
            if job.state == JobState.COMPLETED and job.is_download_available():
                return job
        return None

    def update(self, job_id: str, **changes: Any) -> Job | None:
        updates: dict[str, str] = {}
        for key, value in changes.items():
            if key == "preset" and value is not None:
                updates["preset"] = json.dumps(value, sort_keys=True)
                updates["preset_signature"] = preset_signature(value)
            elif key == "progress":
                updates["progress"] = json.dumps(value or {})
            elif key == "cancel_requested":
                updates["cancel_requested"] = "1" if value else "0"
            elif key == "state" and value is not None:
                updates["state"] = value.value if isinstance(value, JobState) else str(value)
            else:
                updates[key] = "" if value is None else str(value)

        if updates:
            self.client.hset(f"job:{job_id}", mapping=updates)
        return self.get(job_id)
