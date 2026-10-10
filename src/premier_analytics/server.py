"""ASGI entry point: `uvicorn premier_analytics.server:app`. Loads .env, then builds the app.

PA_AI selects the models:
  on      (default) Microsoft Foundry deployments from .env
  off     template overlays only, no model calls
  fake    scripted offline models (deterministic; end-to-end tests and offline demos)
  down    every model call fails (shows the fast path surviving an outage)
PA_STATIC points at the built frontend (defaults to web/dist when it exists).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

from .app import create_app
from .demo_llm import down_llm, scripted_llm

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

mode = os.environ.get("PA_AI", "on")
llm = {"off": None, "fake": scripted_llm(), "down": down_llm()}.get(mode, "env")
static = os.environ.get("PA_STATIC") or (ROOT / "web" / "dist")
app = create_app(
    llm=llm, live_session=False, static_dir=static if Path(static).is_dir() else None,
    max_sessions=int(os.environ.get("PA_MAX_SESSIONS", "4")),
)
