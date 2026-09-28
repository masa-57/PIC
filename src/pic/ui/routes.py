"""Web UI routes. Pages render Jinja2 templates; htmx requests get fragments."""

import hmac

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from pic.config import settings
from pic.core.auth import AuthMode, get_auth_mode
from pic.ui.auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    require_ui_session,
    safe_next,
    session_token,
)
from pic.ui.templating import templates

router = APIRouter(prefix="/ui", dependencies=[Depends(require_ui_session)], include_in_schema=False)
public_router = APIRouter(prefix="/ui", include_in_schema=False)
legacy_router = APIRouter(include_in_schema=False)


@legacy_router.get("/api/v1/clusters/view")
async def legacy_cluster_view() -> RedirectResponse:
    """The old server-rendered cluster page moved to the web UI."""
    return RedirectResponse("/ui", status_code=307)


@public_router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next_path: str = Query("/ui", alias="next")) -> Response:
    if get_auth_mode() != AuthMode.ENABLED:
        return RedirectResponse(safe_next(next_path), status_code=303)
    return templates.TemplateResponse(request, "login.html", {"next": safe_next(next_path), "error": None})


@public_router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    api_key: str = Form(""),
    next_path: str = Form("/ui", alias="next"),
) -> Response:
    target = safe_next(next_path)
    if get_auth_mode() != AuthMode.ENABLED:
        return RedirectResponse(target, status_code=303)
    if not hmac.compare_digest(api_key.encode(), settings.api_key.encode()):
        return templates.TemplateResponse(
            request, "login.html", {"next": target, "error": "Wrong API key"}, status_code=401
        )
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        session_token(settings.api_key),
        max_age=SESSION_MAX_AGE,
        path="/ui",
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
    )
    return response


@public_router.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/ui/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/ui")
    return response
