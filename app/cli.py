from __future__ import annotations
import argparse
import asyncio
import json
from typing import Optional
import aiohttp

from app.config import load_config
from app.storage.settings_store import SettingsStore


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


async def cmd_show() -> None:
    cfg = load_config()
    store = SettingsStore(cfg.settings_file, default_interval=cfg.post_interval_minutes, default_filter_id=cfg.filter_id)
    await store.load()
    _print(store.settings.to_dict())


async def cmd_set_interval(minutes: int) -> None:
    cfg = load_config()
    store = SettingsStore(cfg.settings_file, default_interval=cfg.post_interval_minutes, default_filter_id=cfg.filter_id)
    await store.load()
    await store.update(tags_raw=None, interval=minutes, filter_id=store.settings.filter_id)
    _print({"ok": True, "post_interval_minutes": store.settings.post_interval_minutes})


async def cmd_set_filter(value: str) -> None:
    cfg = load_config()
    store = SettingsStore(cfg.settings_file, default_interval=cfg.post_interval_minutes, default_filter_id=cfg.filter_id)
    await store.load()
    filter_id = None if value.lower() in {"none", "null", "off", "0"} else int(value)
    await store.update(tags_raw=None, interval=None, filter_id=filter_id)
    _print({"ok": True, "filter_id": store.settings.filter_id})


async def cmd_set_tags(text: str) -> None:
    cfg = load_config()
    store = SettingsStore(cfg.settings_file, default_interval=cfg.post_interval_minutes, default_filter_id=cfg.filter_id)
    await store.load()
    await store.update(tags_raw=text, interval=None, filter_id=store.settings.filter_id)
    _print({"ok": True, "tags": store.settings.tags})


async def _login(session: aiohttp.ClientSession, base_url: str, user: str, password: str) -> None:
    # cookie-based login via form
    async with session.post(f"{base_url}/auth/login", data={"user": user, "password": password}, allow_redirects=False) as resp:
        if resp.status not in (302, 303):
            raise RuntimeError(f"Login failed, status={resp.status}")


async def cmd_post_now(base_url: Optional[str]) -> None:
    cfg = load_config()
    base_url = base_url or f"http://{cfg.web_host}:{cfg.web_port}"
    async with aiohttp.ClientSession() as session:
        await _login(session, base_url, cfg.admin_user, cfg.admin_password)
        async with session.post(f"{base_url}/api/post-now") as resp:
            if resp.status != 200:
                raise RuntimeError(f"POST /api/post-now failed: {resp.status}")
            _print(await resp.json())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="derpi-bot-cli", description="CLI for Derpi Bot settings & actions")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("show", help="Show current settings.json")

    si = sub.add_parser("set-interval", help="Set posting interval minutes")
    si.add_argument("minutes", type=int)

    sf = sub.add_parser("set-filter", help="Set Derpibooru filter_id or 'none'")
    sf.add_argument("value", type=str)

    st = sub.add_parser("set-tags", help="Set tag groups. Use \\n for new group.")
    st.add_argument("text", type=str)

    pn = sub.add_parser("post-now", help="Trigger immediate posting via Web API (admin)")
    pn.add_argument("--base-url", type=str, default=None)

    return p


async def _amain(args: argparse.Namespace) -> None:
    if args.cmd == "show":
        await cmd_show()
    elif args.cmd == "set-interval":
        await cmd_set_interval(args.minutes)
    elif args.cmd == "set-filter":
        await cmd_set_filter(args.value)
    elif args.cmd == "set-tags":
        await cmd_set_tags(args.text)
    elif args.cmd == "post-now":
        await cmd_post_now(args.base_url)
    else:
        raise RuntimeError("Unknown command")


def run() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(_amain(args))


if __name__ == "__main__":
    run()
