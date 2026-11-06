from __future__ import annotations

from fastapi import Request

from ..context import Context


def ctx(request: Request) -> Context:
    return request.app.state.ctx
