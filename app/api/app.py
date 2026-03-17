"""
app/api/app.py — FastAPI application factory.

Creates and configures the FastAPI app with all routes and middleware.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router
from app.config import get_settings
from app.db.database import init_db

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    The dashboard serves a VERY VISIBLE warning banner when live trading is on.
    """
    settings = get_settings()

    app = FastAPI(
        title="Trading Bot Dashboard",
        description="EV-based algorithmic trading bot — paper mode by default",
        version="1.0.0",
    )

    # Initialise database
    init_db()

    # Mount templates
    if _TEMPLATES_DIR.exists():
        app.state.templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    # Store settings reference for route access
    app.state.settings = settings

    # Register routes
    app.include_router(router)

    return app
