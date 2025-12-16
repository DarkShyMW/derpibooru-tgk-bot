from __future__ import annotations
import asyncio
import logging
import sys
from aiohttp import web

from app.config import load_config
from app.storage.settings_store import SettingsStore
from app.storage.sent_store import SentImageStore
from app.services.derpi import DerpiClient
from app.services.telegram_client import TelegramClient
from app.services.autoposter import AutoPoster
from app.web.ws import WsHub
from app.web.app_factory import create_web_app


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


async def main():
    setup_logging()
    cfg = load_config()

    settings_store = SettingsStore(
        cfg.settings_file,
        default_interval=cfg.post_interval_minutes,
        default_filter_id=cfg.filter_id
    )
    await settings_store.load()

    sent_store = SentImageStore(cfg.sent_images_file)

    derpi = DerpiClient(
        token=cfg.derpibooru_token,
        search_url=cfg.derpi_search_url,
        filter_id=cfg.filter_id,
        http_pool_limit=cfg.http_pool_limit,
    )
    await derpi.start()

    tg = TelegramClient(cfg.telegram_token, cfg.channel_id)

    try:
        chat = await tg._bot.get_chat(cfg.channel_id)
        print("OK chat:", chat.id, chat.title)
    except Exception as e:
        print("Cannot access chat_id:", cfg.channel_id, "error:", repr(e))


    ws_hub = WsHub()
    autoposter = AutoPoster(tg=tg, derpi=derpi, sent=sent_store, settings=settings_store, ws=ws_hub)
    await autoposter.start()

    app = create_web_app(cfg=cfg, settings_store=settings_store, sent_store=sent_store, autoposter=autoposter, ws_hub=ws_hub)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=cfg.web_host, port=cfg.web_port)
    await site.start()

    logging.info("Web: http://%s:%s", cfg.web_host, cfg.web_port)

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await autoposter.stop()
        await derpi.close()
        await tg.close()
        await runner.cleanup()
        


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
