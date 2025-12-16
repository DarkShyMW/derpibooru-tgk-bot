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
