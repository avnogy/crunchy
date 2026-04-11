from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates

from app.auth import require_basic_auth
from app.config import ensure_app_password, load_settings
from app.logging import setup_logging
from app.transcode import run_job
from app.web.home import router as home_router
from app.web.items import router as items_router
from app.web.jobs import router as jobs_router
from app.web.settings import router as settings_router
from app.worker import JobWorker

settings = load_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)
ensure_app_password(settings)
settings.transcoding_temp_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)

DEFAULT_PRESETS = {
    "480p-low": {
        "maxHeight": 480,
        "videoBitrate": 800000,
        "audioBitrate": 64000,
        "name": "480p Low",
    },
    "480p-medium": {
        "maxHeight": 480,
        "videoBitrate": 1200000,
        "audioBitrate": 96000,
        "name": "480p Medium",
    },
    "480p-high": {
        "maxHeight": 480,
        "videoBitrate": 1600000,
        "audioBitrate": 128000,
        "name": "480p High",
    },
    "720p-low": {
        "maxHeight": 720,
        "videoBitrate": 1400000,
        "audioBitrate": 96000,
        "name": "720p Low",
    },
    "720p-medium": {
        "maxHeight": 720,
        "videoBitrate": 2000000,
        "audioBitrate": 128000,
        "name": "720p Medium",
    },
    "720p-high": {
        "maxHeight": 720,
        "videoBitrate": 2800000,
        "audioBitrate": 128000,
        "name": "720p High",
    },
    "1080p-low": {
        "maxHeight": 1080,
        "videoBitrate": 2600000,
        "audioBitrate": 96000,
        "name": "1080p Low",
    },
    "1080p-medium": {
        "maxHeight": 1080,
        "videoBitrate": 3600000,
        "audioBitrate": 128000,
        "name": "1080p Medium",
    },
    "1080p-high": {
        "maxHeight": 1080,
        "videoBitrate": 5000000,
        "audioBitrate": 160000,
        "name": "1080p High",
    },
}

job_queue: asyncio.Queue = asyncio.Queue()
templates = Jinja2Templates(directory="app/web")
WEB_ROOT = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting app with host=%s port=%s log_level=%s workers=%s poll_interval_ms=%s",
        settings.app_host,
        settings.app_port,
        settings.log_level,
        settings.max_concurrent_jobs or 1,
        settings.jobs_poll_interval_ms,
    )
    worker = JobWorker(
        job_queue,
        lambda job: run_job(job, settings),
        workers=settings.max_concurrent_jobs or 1,
    )
    await worker.start()
    yield
    logger.info("Stopping app")
    await worker.stop()


app = FastAPI(
    title="crunchy",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.state.settings = settings
app.state.presets = settings.presets or DEFAULT_PRESETS
app.state.job_queue = job_queue
app.state.templates = templates


@app.get("/healthz")
async def healthcheck():
    logger.debug("Healthcheck requested")
    return {"status": "ok"}


@app.get("/assets/{page}/page.js", dependencies=[Depends(require_basic_auth)])
async def page_asset(page: str):
    asset_path = WEB_ROOT / page / "page.js"
    if not asset_path.is_file():
        logger.warning("Missing page asset requested for page=%s", page)
        raise HTTPException(status_code=404, detail="Asset not found")
    logger.debug("Serving page asset for page=%s", page)
    return FileResponse(asset_path, media_type="application/javascript")


app.include_router(home_router, dependencies=[Depends(require_basic_auth)])
app.include_router(items_router, dependencies=[Depends(require_basic_auth)])
app.include_router(jobs_router, dependencies=[Depends(require_basic_auth)])
app.include_router(settings_router, dependencies=[Depends(require_basic_auth)])
