from __future__ import annotations

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import BufferedInputFile

import aiohttp

from app.models import ImageRecord


MAX_CAPTION = 1024


def _clip_caption(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= MAX_CAPTION:
        return text
    return text[: MAX_CAPTION - 1] + "…"


class TelegramClient:
    def __init__(self, token: str, channel_id: int, *, http_limit: int = 64):
        # AiohttpSession — стандартная сессия aiogram, можно увеличить лимит коннектов
        # для скорости и стабильности. :contentReference[oaicite:3]{index=3}
        self._session = AiohttpSession(limit=http_limit)
        self._bot = Bot(token=token, session=self._session)
        self._channel_id = channel_id

        # отдельная сессия для скачивания картинок (можно и общую сделать, но так проще/чище)
        self._dl = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25))

    async def close(self) -> None:
        await self._dl.close()
        await self._session.close()

    async def send_image(self, record: ImageRecord) -> None:
        caption_parts = []
        if record.author:
            caption_parts.append(f"Автор: {record.author}")
        if record.source:
            caption_parts.append(f"Источник: {record.source}")
        if record.tags:
            caption_parts.append(f"Теги: {', '.join(record.tags[:20])}")

        caption = _clip_caption("\n".join(caption_parts))

        # Скачиваем сами -> отправляем буфером (максимально надёжно)
        async with self._dl.get(record.url) as r:
            r.raise_for_status()
            data = await r.read()

        photo = BufferedInputFile(data, filename="image.jpg")

        await self._bot.send_photo(
            chat_id=self._channel_id,
            photo=photo,
            caption=caption or None,
        )
