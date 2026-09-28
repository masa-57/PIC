"""Jinja2 environment shared by UI routes."""

import hashlib

from fastapi.templating import Jinja2Templates

from pic.core.auth import AuthMode, get_auth_mode
from pic.services.browse import summarize_result
from pic.ui import STATIC_DIR, TEMPLATES_DIR


def _static_version() -> str:
    """Short hash of the static files, so a changed file gets a new URL despite long caching."""
    digest = hashlib.sha256()
    for path in sorted(STATIC_DIR.iterdir()):
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


static_version = _static_version()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["static_version"] = static_version
templates.env.globals["auth_enabled"] = lambda: get_auth_mode() == AuthMode.ENABLED
templates.env.globals["summarize"] = summarize_result
