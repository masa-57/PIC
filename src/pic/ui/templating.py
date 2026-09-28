"""Jinja2 environment shared by UI routes."""

from fastapi.templating import Jinja2Templates

from pic.core.auth import AuthMode, get_auth_mode
from pic.services.browse import summarize_result
from pic.ui import TEMPLATES_DIR

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["auth_enabled"] = lambda: get_auth_mode() == AuthMode.ENABLED
templates.env.globals["summarize"] = summarize_result
