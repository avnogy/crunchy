from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

AUTH_USERNAME = "admin"

logger = logging.getLogger(__name__)
security = HTTPBasic(realm="crunchy")


def require_basic_auth(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
) -> None:
    settings = request.app.state.settings
    username_ok = secrets.compare_digest(
        credentials.username.encode("utf8"),
        AUTH_USERNAME.encode("utf8"),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf8"),
        settings.app_password.encode("utf8"),
    )
    if username_ok and password_ok:
        return

    logger.warning("Rejected unauthorized request for path=%s", request.url.path)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
        headers={"WWW-Authenticate": "Basic"},
    )
