from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from mimetypes import guess_type
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates

from app.auth import require_basic_auth
from app.config import ensure_app_password, load_settings
from app.logging import setup_logging
from app.paths import ensure_managed_directories
from app.web.home import router as home_router
from app.web.items import router as items_router
from app.web.jobs import router as jobs_router
from app.web.settings import router as settings_router

settings = load_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)
ensure_app_password(settings)
ensure_managed_directories()

templates = Jinja2Templates(directory="app/web")
WEB_ROOT = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    current_settings = app.state.settings
    logger.info(
        "Starting app with host=%s port=%s log_level=%s",
        current_settings.app_host,
        current_settings.app_port,
        current_settings.log_level,
    )
    yield
    logger.info("Stopping app")


app = FastAPI(
    title="crunchy",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.state.settings = settings
app.state.templates = templates


@app.get("/healthz")
async def healthcheck():
    logger.debug("Healthcheck requested")
    return {"status": "ok"}


@app.get("/assets/{asset_path:path}", dependencies=[Depends(require_basic_auth)])
async def asset_file(asset_path: str):
    file_path = WEB_ROOT / asset_path
    if not file_path.is_file() or WEB_ROOT not in file_path.resolve().parents:
        logger.warning("Missing asset requested for path=%s", asset_path)
        raise HTTPException(status_code=404, detail="Asset not found")
    media_type = guess_type(file_path.name)[0] or "application/octet-stream"
    logger.debug("Serving asset for path=%s", asset_path)
    return FileResponse(file_path, media_type=media_type)


app.include_router(home_router, dependencies=[Depends(require_basic_auth)])
app.include_router(items_router, dependencies=[Depends(require_basic_auth)])
app.include_router(jobs_router, dependencies=[Depends(require_basic_auth)])
app.include_router(settings_router, dependencies=[Depends(require_basic_auth)])
