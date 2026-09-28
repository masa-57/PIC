"""Cookie session for the web UI. The JSON API keeps using the X-API-Key header.

The cookie holds an HMAC of PIC_API_KEY, never the key itself, so rotating the
key ends every session and there is no server-side session store.
"""

import hashlib
import hmac
from urllib.parse import quote

from fastapi import HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from pic.config import settings
from pic.core.auth import AuthMode, get_auth_mode

SESSION_COOKIE = "pic_session"
SESSION_MAX_AGE = 30 * 24 * 3600
LOGIN_PATH = "/ui/login"


class LoginRequiredError(Exception):
    """Raised by ``require_ui_session``; turned into a redirect by ``login_required_handler``."""

    def __init__(self, next_path: str) -> None:
        super().__init__(next_path)
        self.next_path = next_path


def session_token(api_key: str) -> str:
    return hmac.new(api_key.encode(), b"pic-ui-session", hashlib.sha256).hexdigest()


def is_valid_session(cookie: str | None) -> bool:
    if not cookie or not settings.api_key:
        return False
    return hmac.compare_digest(cookie, session_token(settings.api_key))


def safe_next(path: str | None) -> str:
    """Only allow redirects back into the UI (blocks open redirects such as //evil.example)."""
    if path and path.startswith("/ui") and "\\" not in path:
        return path
    return "/ui"


async def require_ui_session(request: Request) -> None:
    mode = get_auth_mode()
    if mode == AuthMode.DISABLED:
        return
    if mode == AuthMode.MISCONFIGURED:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    if is_valid_session(request.cookies.get(SESSION_COOKIE)):
        return
    raise LoginRequiredError(request.url.path)


async def login_required_handler(request: Request, exc: Exception) -> Response:
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=401, headers={"HX-Redirect": LOGIN_PATH})
    next_path = exc.next_path if isinstance(exc, LoginRequiredError) else "/ui"
    return RedirectResponse(f"{LOGIN_PATH}?next={quote(next_path, safe='/')}", status_code=303)


async def require_htmx(request: Request) -> None:
    """State-changing UI routes need htmx's header; cross-site forms cannot set it."""
    if request.headers.get("HX-Request") != "true":
        raise HTTPException(status_code=400, detail="Missing HX-Request header")
