from __future__ import annotations

import hmac
from urllib.parse import parse_qs

from starlette.responses import JSONResponse


class TokenMiddleware:
    """Every HTTP request and WebSocket must carry the per-launch secret.

    The token comes from the ``X-RecPro-Token`` header, or the ``t`` query parameter for
    <img>/<video> sources and WebSockets (which can't set headers). CORS preflights pass
    through so the CORS middleware can answer them.
    """

    def __init__(self, app, token: str):
        self.app = app
        self.token = token.encode()

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        if kind == "http" and scope.get("method") == "OPTIONS":
            return await self.app(scope, receive, send)

        provided: bytes | None = None
        for k, v in scope.get("headers", []):
            if k == b"x-recpro-token":
                provided = v
                break
        if provided is None:
            qs = parse_qs(scope.get("query_string", b"").decode("latin-1"))
            t = qs.get("t", [None])[0]
            if t:
                provided = t.encode()

        if provided is None or not hmac.compare_digest(provided, self.token):
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 4401})
                return
            resp = JSONResponse({"detail": "unauthorized"}, status_code=401)
            return await resp(scope, receive, send)
        return await self.app(scope, receive, send)
