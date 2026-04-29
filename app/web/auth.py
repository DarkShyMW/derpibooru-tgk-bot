from __future__ import annotations
import base64
import hmac
import hashlib
import time
import secrets
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
        # Use constant-time comparison to prevent timing attacks
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


def generate_csrf_token(secret: str) -> str:
    """Generate a CSRF token using HMAC."""
    timestamp = int(time.time())
    random_bytes = secrets.token_hex(16)
    payload = f"{timestamp}:{random_bytes}"
    sig = _sign(secret, payload)
    return f"{payload}:{sig}"


def validate_csrf_token(secret: str, token: str) -> bool:
    """Validate a CSRF token using constant-time comparison."""
    try:
        parts = token.split(":", 2)
        if len(parts) != 3:
            return False
        timestamp_str, random_bytes, sig = parts
        payload = f"{timestamp_str}:{random_bytes}"
        # Check if token is older than 1 hour
        timestamp = int(timestamp_str)
        if abs(int(time.time()) - timestamp) > 3600:
            return False
        # Use constant-time comparison
        return hmac.compare_digest(sig, _sign(secret, payload))
    except Exception:
        return False


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


# Rate limiting storage (in-memory)
_login_attempts: dict[str, list[float]] = {}
_rate_limit_lock: Optional[asyncio.Lock] = None


def get_rate_limit_lock() -> asyncio.Lock:
    global _rate_limit_lock
    if _rate_limit_lock is None:
        _rate_limit_lock = asyncio.Lock()
    return _rate_limit_lock


async def check_rate_limit(identifier: str, max_attempts: int = 5, window_seconds: int = 300) -> bool:
    """Check if the identifier has exceeded rate limit. Returns True if allowed."""
    import asyncio
    lock = get_rate_limit_lock()
    async with lock:
        now = time.time()
        if identifier not in _login_attempts:
            _login_attempts[identifier] = []
        
        # Remove old attempts outside the window
        _login_attempts[identifier] = [t for t in _login_attempts[identifier] if now - t < window_seconds]
        
        if len(_login_attempts[identifier]) >= max_attempts:
            return False
        
        _login_attempts[identifier].append(now)
        return True


async def record_failed_login(identifier: str) -> None:
    """Record a failed login attempt."""
    import asyncio
    lock = get_rate_limit_lock()
    async with lock:
        now = time.time()
        if identifier not in _login_attempts:
            _login_attempts[identifier] = []
        _login_attempts[identifier].append(now)
