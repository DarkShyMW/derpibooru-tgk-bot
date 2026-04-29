from __future__ import annotations
import asyncio
import json
from aiohttp import web
from typing import Any, Dict, Set


class WsHub:
    def __init__(self):
        self._clients: Set[web.WebSocketResponse] = set()
        self._lock = asyncio.Lock()

    async def register(self, ws: web.WebSocketResponse) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def unregister(self, ws: web.WebSocketResponse) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, event: str, data: Dict[str, Any]) -> None:
        message = json.dumps({"event": event, "data": data}, ensure_ascii=False)
        dead = []
        async with self._lock:
            for ws in self._clients:
                if ws.closed:
                    dead.append(ws)
                    continue
                try:
                    await ws.send_str(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)


def ws_origin_check_middleware(allowed_origins: tuple[str, ...] = ()):
    """Middleware to check WebSocket Origin header for CSRF protection."""
    @web.middleware
    async def mw(request: web.Request, handler):
        # Only check WebSocket upgrade requests
        if request.path == "/ws" and request.headers.get("Upgrade", "").lower() == "websocket":
            origin = request.headers.get("Origin", "")
            host = request.headers.get("Host", "")
            
            # If allowed_origins is configured, check against it
            if allowed_origins:
                if origin not in allowed_origins:
                    return web.json_response({"error": "origin not allowed"}, status=403)
            else:
                # Default: check that Origin matches Host (same-origin policy)
                if origin:
                    # Parse origin to get hostname
                    origin_host = origin.replace("https://", "").replace("http://", "").split(":")[0]
                    request_host = host.split(":")[0]
                    if origin_host != request_host and origin_host != "localhost" and origin_host != "127.0.0.1":
                        return web.json_response({"error": "origin mismatch"}, status=403)
        
        return await handler(request)
    return mw
