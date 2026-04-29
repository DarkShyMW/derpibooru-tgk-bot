from __future__ import annotations
import json
import hmac
from contextlib import suppress
from aiohttp import web
from app.storage.settings_store import parse_tag_lines
from app.web.auth import check_rate_limit, record_failed_login, generate_csrf_token, validate_csrf_token

MAX_IMAGES_EXPOSE = 200


def setup_routes(app: web.Application) -> None:
    # pages
    app.router.add_get("/", index)
    app.router.add_get("/viewer", viewer_page)
    app.router.add_get("/settings", settings_page)
    app.router.add_get("/login", login_page)
    app.router.add_post("/auth/login", do_login)
    app.router.add_post("/auth/logout", do_logout)

    # ws
    app.router.add_get("/ws", ws_handler)

    # api
    app.router.add_get("/api/images", api_images)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/settings", api_get_settings)
    app.router.add_post("/api/settings", api_update_settings)
    app.router.add_post("/api/post-now", api_post_now)

    # static
    app.router.add_static("/static/", app["static_dir"], show_index=False)


async def index(request: web.Request) -> web.Response:
    return web.FileResponse(request.app["tpl_dir"] / "index.html")


async def viewer_page(request: web.Request) -> web.Response:
    return web.FileResponse(request.app["tpl_dir"] / "viewer.html")


async def settings_page(request: web.Request) -> web.Response:
    return web.FileResponse(request.app["tpl_dir"] / "settings.html")


async def login_page(request: web.Request) -> web.Response:
    cfg = request.app["config"]
    # Generate CSRF token for the login form
    csrf_token = generate_csrf_token(cfg.session_secret)
    response = web.FileResponse(request.app["tpl_dir"] / "login.html")
    # Store CSRF token in a cookie (httponly=False so JS can access it if needed, but we'll use hidden field)
    response.set_cookie("csrf_token", csrf_token, httponly=False, samesite="Strict", max_age=3600)
    return response


async def do_login(request: web.Request) -> web.Response:
    cfg = request.app["config"]
    
    # Rate limiting: use IP address as identifier
    ip_address = request.remote or "unknown"
    identifier = f"login:{ip_address}"
    
    # Check rate limit before processing
    if not await check_rate_limit(identifier, max_attempts=5, window_seconds=300):
        return web.HTTPFound("/login?error=ratelimit")
    
    data = await request.post()
    user = (data.get("user") or "").strip()
    password = (data.get("password") or "").strip()
    
    # Validate CSRF token
    csrf_token = data.get("csrf_token", "")
    stored_csrf = request.cookies.get("csrf_token", "")
    if not validate_csrf_token(cfg.session_secret, csrf_token) or not validate_csrf_token(cfg.session_secret, stored_csrf):
        await record_failed_login(identifier)
        return web.HTTPFound("/login?error=csrf")

    role = None
    redirect_to = "/viewer"

    # Use constant-time comparison for passwords to prevent timing attacks
    admin_user_match = hmac.compare_digest(user.encode(), cfg.admin_user.encode())
    admin_pass_match = hmac.compare_digest(password.encode(), cfg.admin_password.encode())
    
    if admin_user_match and admin_pass_match:
        role = "admin"
        redirect_to = "/settings"
    elif cfg.viewer_password:
        viewer_user_match = hmac.compare_digest(user.encode(), cfg.viewer_user.encode())
        viewer_pass_match = hmac.compare_digest(password.encode(), cfg.viewer_password.encode())
        if viewer_user_match and viewer_pass_match:
            role = "viewer"
            redirect_to = "/viewer"

    if role:
        cookie = request.app["make_session"](user, role)
        resp = web.HTTPFound(redirect_to)
        # Set Secure flag when using HTTPS, Strict SameSite for critical operations
        resp.set_cookie("session", cookie, httponly=True, samesite="Strict", secure=True)
        # Clear CSRF token cookie after successful login
        resp.del_cookie("csrf_token")
        return resp

    # Record failed login attempt
    await record_failed_login(identifier)
    return web.HTTPFound("/login?error=1")


async def do_logout(request: web.Request) -> web.Response:
    resp = web.HTTPFound("/")
    resp.del_cookie("session")
    return resp


async def ws_handler(request: web.Request) -> web.StreamResponse:
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)

    hub = request.app["ws"]
    await hub.register(ws)

    # initial status
    autoposter = request.app["autoposter"]
    await hub.broadcast("status", {
        "next_run_at": autoposter.next_run_at.isoformat() if autoposter.next_run_at else None,
        "interval_minutes": request.app["settings"].settings.post_interval_minutes,
    })

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                pass
    finally:
        await hub.unregister(ws)

    return ws


async def api_images(request: web.Request) -> web.Response:
    sent = request.app["sent"]
    try:
        limit = min(MAX_IMAGES_EXPOSE, max(1, int(request.query.get("limit", "120"))))
    except Exception:
        limit = 120
    return web.json_response({"ok": True, "images": sent.recent(limit)})


async def api_status(request: web.Request) -> web.Response:
    autoposter = request.app["autoposter"]
    settings = request.app["settings"].settings
    return web.json_response({
        "ok": True,
        "next_run_at": autoposter.next_run_at.isoformat() if autoposter.next_run_at else None,
        "interval_minutes": settings.post_interval_minutes,
    })


async def api_get_settings(request: web.Request) -> web.Response:
    settings = request.app["settings"].settings
    autoposter = request.app["autoposter"]
    payload = settings.to_dict()
    payload["next_run_at"] = autoposter.next_run_at.isoformat() if autoposter.next_run_at else None
    payload["tags_text"] = settings.tags_text()
    return web.json_response({"ok": True, "settings": payload})


async def api_update_settings(request: web.Request) -> web.Response:
    store = request.app["settings"]
    autoposter = request.app["autoposter"]

    payload = await request.json()
    interval_raw = payload.get("post_interval_minutes")
    filter_raw = payload.get("filter_id")
    tags_raw = payload.get("tags_raw", "")

    interval = None
    with suppress(Exception):
        if interval_raw is not None:
            interval = int(interval_raw)

    if filter_raw == "" or filter_raw is None:
        filter_id = None
    else:
        filter_id = None
        with suppress(Exception):
            filter_id = int(filter_raw)

    await store.update(tags_raw=tags_raw, interval=interval, filter_id=filter_id)
    autoposter.notify_settings_changed()

    return web.json_response({"ok": True})


async def api_post_now(request: web.Request) -> web.Response:
    autoposter = request.app["autoposter"]
    payload = {}
    if request.can_read_body:
        with suppress(json.JSONDecodeError):
            payload = await request.json()

    tags_override = None
    if isinstance(payload, dict) and payload.get("tags_raw"):
        parsed = parse_tag_lines(payload["tags_raw"])
        tags_override = parsed[0] if parsed else None

    await autoposter.post_now(tags_override)
    return web.json_response({"ok": True})
