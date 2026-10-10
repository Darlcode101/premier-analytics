"""ASGI entry point: `uvicorn premier_analytics.server:app`. Loads .env, then builds the app.

Set PA_AI=off to run with template overlays only (no model calls, no cost).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

from .app import create_app

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
app = create_app(llm=None if os.environ.get("PA_AI", "on") == "off" else "env", live_session=False)
