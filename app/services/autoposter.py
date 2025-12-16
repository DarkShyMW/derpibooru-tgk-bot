from __future__ import annotations
import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from app.storage.settings_store import SettingsStore, parse_tag_lines
from app.storage.sent_store import SentImageStore
from app.services.derpi import DerpiClient
from app.services.telegram_client import TelegramClient
from app.web.ws import WsHub


class AutoPoster:
    def __init__(self, *, tg: TelegramClient, derpi: DerpiClient, sent: SentImageStore, settings: SettingsStore, ws: WsHub):
        self._tg = tg
        self._derpi = derpi
        self._sent = sent
        self._settings = settings
        self._ws = ws

        self._queue: asyncio.Queue[Optional[List[str]]] = asyncio.Queue()
        self._stop = asyncio.Event()
        self._changed = asyncio.Event()

        self._worker: asyncio.Task | None = None
        self._scheduler: asyncio.Task | None = None

        self.next_run_at: datetime | None = None

    async def start(self) -> None:
        self._worker = asyncio.create_task(self._post_loop(), name="post-loop")
        self._scheduler = asyncio.create_task(self._scheduler_loop(), name="scheduler-loop")
        await self.post_now()

    async def stop(self) -> None:
        self._stop.set()
        self._changed.set()
        await self._queue.put(None)
        for t in (self._worker, self._scheduler):
            if t:
                t.cancel()
                with suppress(asyncio.CancelledError):
                    await t

    def notify_settings_changed(self) -> None:
        self._changed.set()

    async def post_now(self, tags: Optional[List[str]] = None) -> None:
        await self._queue.put(tags)

    async def _scheduler_loop(self) -> None:
        while not self._stop.is_set():
            interval = max(1, int(self._settings.settings.post_interval_minutes))
            self.next_run_at = datetime.now(timezone.utc) + timedelta(minutes=interval)

            await self._ws.broadcast("status", {
                "next_run_at": self.next_run_at.isoformat(),
                "interval_minutes": interval,
            })

            wait_s = max(1, (self.next_run_at - datetime.now(timezone.utc)).total_seconds())
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=wait_s)
                self._changed.clear()
                continue
            except asyncio.TimeoutError:
                await self._queue.put(None)

    async def _post_loop(self) -> None:
        while not self._stop.is_set():
            tags = await self._queue.get()
            if self._stop.is_set():
                break
            await self._post(tags)

    async def _post(self, tags: Optional[List[str]]) -> None:
        chosen = tags or self._settings.settings.pick_random_tags()
        record = await self._derpi.fetch_random_image(chosen, skip_urls=self._sent.known_urls)
        if not record:
            await self._ws.broadcast("toast", {"type": "warn", "message": f"Нет свежих картинок для: {chosen}"})
            return

        try:
            await self._tg.send_image(record)
            await self._sent.add(record)

            await self._ws.broadcast("new_image", {"record": record.to_dict()})
            await self._ws.broadcast("toast", {"type": "ok", "message": "Картинка отправлена ✅"})
        except Exception as e:
            await self._ws.broadcast("toast", {"type": "error", "message": f"Ошибка отправки: {e}"})
