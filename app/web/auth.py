from __future__ import annotations
import base64
import hmac
import hashlib
import time
from dataclasses import dataclass
from aiohttp import web
from typing import Optional


@dataclass(frozen=True)
class Session:
    user: str
    role: str  # "admin" | "viewer"
    exp: int


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session_cookie(*, secret: str, user: str, role: str, ttl_seconds: int) -> str:
    exp = int(time.time()) + ttl_seconds
    payload = f"{user}|{role}|{exp}"
    sig = _sign(secret, payload)
    raw = f"{payload}|{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def parse_session_cookie(*, secret: str, cookie: str) -> Optional[Session]:
    try:
        raw = base64.urlsafe_b64decode(cookie.encode()).decode()
        user, role, exp, sig = raw.split("|", 3)
        payload = f"{user}|{role}|{exp}"
        if not hmac.compare_digest(sig, _sign(secret, payload)):
            return None
        exp_i = int(exp)
        if exp_i < int(time.time()):
            return None
        if role not in {"admin", "viewer"}:
            return None
        return Session(user=user, role=role, exp=exp_i)
    except Exception:
        return None


def session_middleware(secret: str):
    @web.middleware
    async def mw(request: web.Request, handler):
        request["session"] = None
        cookie = request.cookies.get("session")
        if cookie:
            request["session"] = parse_session_cookie(secret=secret, cookie=cookie)
        return await handler(request)
    return mw


def require_login_middleware(protected_prefixes: tuple[str, ...]):
    @web.middleware
    async def mw(request: web.Request, handler):
        if any(request.path.startswith(p) for p in protected_prefixes):
            sess = request.get("session")
            if not sess:
                if request.path.startswith("/api/"):
                    return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
                raise web.HTTPFound("/login")
        return await handler(request)
    return mw


def require_role_middleware(prefix_role_map: dict[str, str]):
    @web.middleware
    async def mw(request: web.Request, handler):
        for prefix, required in prefix_role_map.items():
            if request.path.startswith(prefix):
                sess = request.get("session")
                if not sess:
                    if request.path.startswith("/api/"):
                        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
                    raise web.HTTPFound("/login")
                if sess.role != required:
                    if request.path.startswith("/api/"):
                        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
                    raise web.HTTPFound("/login?forbidden=1")
        return await handler(request)
    return mw
