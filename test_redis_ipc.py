from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.ffmpeg_worker import _build_ffmpeg_args
from app.jobs import JobState, RedisJobStore, new_job


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.lists: dict[str, list[str]] = {}

    def pipeline(self):
        return FakePipeline(self)

    def hset(self, key: str, mapping: dict[str, str]) -> None:
        self.hashes.setdefault(key, {}).update(mapping)

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    def lpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).insert(0, value)

    def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = self.lists.get(key, [])
        if end == -1:
            end = len(values) - 1
        return values[start : end + 1]


class FakePipeline:
    def __init__(self, client: FakeRedis) -> None:
        self.client = client
        self.calls: list[tuple[str, tuple, dict]] = []

    def hset(self, *args, **kwargs):
        self.calls.append(("hset", args, kwargs))
        return self

    def lpush(self, *args, **kwargs):
        self.calls.append(("lpush", args, kwargs))
        return self

    def rpush(self, *args, **kwargs):
        self.calls.append(("rpush", args, kwargs))
        return self

    def execute(self) -> None:
        for name, args, kwargs in self.calls:
            getattr(self.client, name)(*args, **kwargs)


class RedisIpcTests(unittest.TestCase):
    def test_store_round_trip_and_dedupe(self) -> None:
        client = FakeRedis()
        store = RedisJobStore(client)
        job = new_job(
            item_id="item-1",
            item_name="A Name",
            preset={"name": "720p", "videoCodec": "h264"},
        )
        payload = {"job_id": job.id, "input_url": "http://example", "output_path": "/tmp/out.mp4"}

        store.add(job, payload)

        loaded = store.get(job.id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.state, JobState.QUEUED)
        self.assertEqual(loaded.item_id, "item-1")

        reusable = store.find_reusable_by_item_and_preset(
            "item-1", {"name": "720p", "videoCodec": "h264"}
        )
        self.assertIsNotNone(reusable)
        self.assertEqual(reusable.id, job.id)

        queue_payload = json.loads(client.lists["jobs:queue"][0])
        self.assertEqual(queue_payload["job_id"], job.id)

    def test_completed_job_reports_download_when_file_exists(self) -> None:
        client = FakeRedis()
        store = RedisJobStore(client)
        job = new_job(
            item_id="item-2",
            item_name="Done",
            preset={"name": "720p", "videoCodec": "h264"},
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "done.mp4"
            output_path.write_bytes(b"video")
            store.add(job, {"job_id": job.id, "input_url": "http://example", "output_path": str(output_path)})
            store.update(job.id, state=JobState.COMPLETED, output_path=str(output_path))

            loaded = store.get(job.id)
            assert loaded is not None
            self.assertTrue(loaded.is_download_available())
            self.assertTrue(loaded.to_dict()["download_available"])

    def test_build_ffmpeg_args_uses_explicit_argv(self) -> None:
        args = _build_ffmpeg_args(
            {
                "input_url": "http://example/stream.m3u8",
                "output_path": "/tmp/out.mp4",
                "preset": {
                    "videoCodec": "h264",
                    "audioCodec": "aac",
                    "videoBitrate": 1000,
                    "audioBitrate": 128,
                    "maxHeight": 720,
                },
            }
        )

        self.assertEqual(args[:4], ["ffmpeg", "-y", "-i", "http://example/stream.m3u8"])
        self.assertIn("-vf", args)
        self.assertEqual(args[-1], "/tmp/out.mp4")


if __name__ == "__main__":
    unittest.main()
