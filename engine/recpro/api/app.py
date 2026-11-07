from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..context import Context
from .security import TokenMiddleware

APP_ORIGINS = ["app://ui"]
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def create_app(c: Context, extra_origins: list[str] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        c.events.attach(asyncio.get_running_loop())
        c.start()
        try:
            yield
        finally:
            c.stop()

    app = FastAPI(title="RecPro engine", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.ctx = c

    from . import routes_system

    app.include_router(routes_system.router)
    for mod in _optional_route_modules():
        app.include_router(mod.router)

    # Middleware order: the last added runs first. CORS must answer preflights before auth.
    app.add_middleware(TokenMiddleware, token=c.token)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=APP_ORIGINS + DEV_ORIGINS + list(extra_origins or []),
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
    )
    return app


def _optional_route_modules():
    """Route modules are added as milestones land; import lazily so a broken one is obvious."""
    import importlib

    names = [
        "routes_library",
        "routes_media",
        "routes_ops",
        "routes_people",
        "routes_search",
        "routes_review",
        "routes_private",
        "routes_labels",
        "routes_models",
        "routes_cleanup",
    ]
    mods = []
    for n in names:
        try:
            mods.append(importlib.import_module(f"recpro.api.{n}"))
        except ModuleNotFoundError as e:
            if e.name == f"recpro.api.{n}":
                continue
            raise
    return mods
