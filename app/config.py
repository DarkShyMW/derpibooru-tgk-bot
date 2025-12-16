from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()


def env(name: str, cast=str, default=None):
    v = os.getenv(name, default)
    if v is None or v == "":
        raise RuntimeError(f"Missing env var: {name}")
    return cast(v)


@dataclass(frozen=True)
class Config:
    telegram_token: str
    channel_id: int

    derpibooru_token: str
    derpi_search_url: str
    filter_id: int

    post_interval_minutes: int

    web_host: str
    web_port: int

    settings_file: Path
    sent_images_file: Path

    http_pool_limit: int

    admin_user: str
    admin_password: str
    session_secret: str
    session_ttl_seconds: int

    viewer_user: str
    viewer_password: str


def load_config() -> Config:
    return Config(
        telegram_token=env("TELEGRAM_TOKEN", str),
        channel_id=env("CHANNEL_ID", int),

        derpibooru_token=env("DERPIBOORU_TOKEN", str),
        derpi_search_url=env("DERPI_SEARCH_URL", str),
        filter_id=env("FILTER_ID", int, 56027),

        post_interval_minutes=env("POST_INTERVAL_MINUTES", int, 60),

        web_host=env("WEB_HOST", str, "0.0.0.0"),
        web_port=env("WEB_PORT", int, 8080),

        settings_file=Path(env("SETTINGS_FILE", str, "settings.json")),
        sent_images_file=Path(env("SENT_IMAGES_FILE", str, "sent_images.json")),

        http_pool_limit=env("HTTP_POOL_LIMIT", int, 64),

        admin_user=env("ADMIN_USER", str, "admin"),
        admin_password=env("ADMIN_PASSWORD", str),
        session_secret=env("SESSION_SECRET", str),
        session_ttl_seconds=env("SESSION_TTL_SECONDS", int, 86400),

        viewer_user=env("VIEWER_USER", str, "viewer"),
        viewer_password=env("VIEWER_PASSWORD", str, ""),
    )
