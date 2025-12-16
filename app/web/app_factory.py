from __future__ import annotations
from aiohttp import web
from pathlib import Path
from app.web.auth import session_middleware, require_login_middleware, require_role_middleware, make_session_cookie
from app.web.routes import setup_routes


def create_web_app(*, cfg, settings_store, sent_store, autoposter, ws_hub) -> web.Application:
    tpl_dir = Path(__file__).parent / "templates"
    static_dir = Path(__file__).parent / "static"

    app = web.Application(middlewares=[
        session_middleware(secret=cfg.session_secret),
        # viewer/admin must be logged-in to access /viewer
        require_login_middleware(protected_prefixes=("/viewer",)),
        # admin-only routes
        require_role_middleware({
            "/settings": "admin",
            "/api/settings": "admin",
            "/api/post-now": "admin",
        }),
    ])

    app["config"] = cfg
    app["settings"] = settings_store
    app["sent"] = sent_store
    app["autoposter"] = autoposter
    app["ws"] = ws_hub
    app["tpl_dir"] = tpl_dir
    app["static_dir"] = static_dir
    app["make_session"] = lambda user, role: make_session_cookie(
        secret=cfg.session_secret,
        user=user,
        role=role,
        ttl_seconds=cfg.session_ttl_seconds,
    )

    setup_routes(app)
    return app
