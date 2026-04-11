from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job:
    def __init__(
        self,
        item_id: str,
        item_name: str,
        preset: dict[str, Any],
    ) -> None:
        self.id = str(uuid.uuid4())
        self.item_id = item_id
        self.item_name = item_name
        self.preset = preset
        self.state = JobState.PENDING
        self.created_at = datetime.utcnow()
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.output_path: Path | None = None
        self.log_path: Path | None = None
        self.process: Any = None
        self.error_message: str | None = self._validate()
        self.speed: str = ""
        self.progress: dict[str, Any] = {}

    def _validate(self) -> str | None:
        if not self.item_id:
            return "item_id is required"
        if not self.item_name:
            return "item_name is required"
        if not self.preset:
            return "preset is required"
        return None

    def start(self) -> None:
        self.state = JobState.RUNNING
        self.started_at = datetime.utcnow()

    def complete(self, output_path: Path) -> None:
        self.state = JobState.COMPLETED
        self.finished_at = datetime.utcnow()
        self.output_path = output_path

    def fail(self, error_message: str) -> None:
        self.state = JobState.FAILED
        self.finished_at = datetime.utcnow()
        self.error_message = error_message

    def cancel(self) -> None:
        self.state = JobState.CANCELLED
        self.finished_at = datetime.utcnow()

    def is_download_available(self) -> bool:
        return bool(self.output_path and self.output_path.exists())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "item_id": self.item_id,
            "item_name": self.item_name,
            "preset": self.preset,
            "state": self.state.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "output_path": str(self.output_path) if self.output_path else None,
            "log_path": str(self.log_path) if self.log_path else None,
            "download_available": self.is_download_available(),
            "error_message": self.error_message,
            "speed": self.speed,
            "progress": self.progress,
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def add(self, job: Job) -> Job:
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def find_reusable_by_item_and_preset(
        self, item_id: str, preset: dict[str, Any]
    ) -> Job | None:
        for job in self._jobs.values():
            if (
                job.item_id == item_id
                and job.preset == preset
                and (
                    job.state in (JobState.PENDING, JobState.RUNNING)
                    or (job.state == JobState.COMPLETED and job.is_download_available())
                )
            ):
                return job
        return None

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)


job_store = JobStore()
