import asyncio
import json
import logging
import os
import random
import re
import sys
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import aiohttp
from aiohttp import web
from telegram import Bot

DERPI_SEARCH_URL = "https://derpibooru.org/api/v1/json/search/images"
SETTINGS_FILE = Path("settings.json")
SENT_IMAGES_FILE = Path("sent_images.json")
DEFAULT_TAG_GROUPS = [["penis"], ["anal"], ["female"], ["vulva"], ["creampie"]]
DEFAULT_INTERVAL_MINUTES = 60
DEFAULT_FILTER_ID = 56027
MAX_IMAGES_EXPOSE = 200

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_TOKEN",
    "7711849755:AAGpXO59jvHHWEWPfF6oA7iYrz9H_rTK2q0",
)
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1002010407572"))
DERPIBOORU_TOKEN = os.getenv("DERPIBOORU_TOKEN", "hY4hYzlpzOLegQl_W2Mx")
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_tag_lines(raw_text: str) -> List[List[str]]:
    groups: List[List[str]] = []
    for line in raw_text.splitlines():
        parts = [p.strip() for p in re.split(r"[ ,]+", line) if p.strip()]
        if parts:
            groups.append(parts)
    return groups


@dataclass
class Settings:
    tags: List[List[str]]
    post_interval_minutes: int
    filter_id: Optional[int] = DEFAULT_FILTER_ID

    @staticmethod
    def _normalize_tags(raw: Any) -> List[List[str]]:
        normalized: List[List[str]] = []
        for group in raw or []:
            if isinstance(group, str):
                group_parts = [
                    p.strip() for p in re.split(r"[ ,]+", group) if p.strip()
                ]
                if group_parts:
                    normalized.append(group_parts)
                continue
            if isinstance(group, list):
                group_parts = [str(p).strip() for p in group if str(p).strip()]
                if group_parts:
                    normalized.append(group_parts)
        return normalized

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Settings":
        tags = cls._normalize_tags(data.get("tags")) or DEFAULT_TAG_GROUPS
        try:
            interval = max(1, int(data.get("post_interval_minutes", DEFAULT_INTERVAL_MINUTES)))
        except (TypeError, ValueError):
            interval = DEFAULT_INTERVAL_MINUTES
        filter_id_raw = data.get("filter_id", DEFAULT_FILTER_ID)
        try:
            filter_id = int(filter_id_raw) if filter_id_raw is not None else None
        except (TypeError, ValueError):
            filter_id = DEFAULT_FILTER_ID
        return cls(tags=tags, post_interval_minutes=interval, filter_id=filter_id)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def tags_text(self) -> str:
        return "\n".join(", ".join(group) for group in self.tags)

    def pick_random_tags(self) -> List[str]:
        if not self.tags:
            return []
        return random.choice(self.tags)


class SettingsManager:
    def __init__(self, path: Path):
        self._path = path
        self.settings = Settings(
            tags=DEFAULT_TAG_GROUPS,
            post_interval_minutes=DEFAULT_INTERVAL_MINUTES,
            filter_id=DEFAULT_FILTER_ID,
        )
        self._lock = asyncio.Lock()

    async def load(self) -> Settings:
        if not self._path.exists():
            await self.save()
            return self.settings

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self.settings = Settings.from_dict(data)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read settings.json, using defaults: %s", exc)
            await self.save()
        return self.settings

    async def save(self) -> Settings:
        payload = self.settings.to_dict()
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        async with self._lock:
            self._path.write_text(text, encoding="utf-8")
        return self.settings

    async def update(
        self,
        *,
        tags_raw: Optional[str] = None,
        interval: Optional[int] = None,
        filter_id: Optional[int] = None,
    ) -> Settings:
        if tags_raw is not None:
            parsed = parse_tag_lines(tags_raw)
            if parsed:
                self.settings.tags = parsed

        if interval is not None and interval > 0:
            self.settings.post_interval_minutes = interval

        if filter_id is not None:
            self.settings.filter_id = filter_id

        await self.save()
        return self.settings


@dataclass
class ImageRecord:
    url: str
    author: Optional[str]
    source: Optional[str]
    tags: List[str]
    posted_at: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "author": self.author,
            "source": self.source,
            "tags": self.tags,
            "posted_at": self.posted_at,
        }


class SentImageStore:
    def __init__(self, path: Path):
        self._path = path
        self._records: List[ImageRecord] = []
        self._known_urls: Set[str] = set()
        self._lock = asyncio.Lock()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to parse sent_images.json, starting fresh: %s", exc)
            return

        for item in raw:
            record: Optional[ImageRecord] = None
            if isinstance(item, str):
                record = ImageRecord(
                    url=item, author=None, source=None, tags=[], posted_at=None
                )
            elif isinstance(item, dict) and "url" in item:
                record = ImageRecord(
                    url=item.get("url"),
                    author=item.get("author"),
                    source=item.get("source"),
                    tags=item.get("tags", []),
                    posted_at=item.get("posted_at"),
                )

            if record and record.url not in self._known_urls:
                self._known_urls.add(record.url)
                self._records.append(record)

    @property
    def known_urls(self) -> Set[str]:
        return self._known_urls

    async def add(self, record: ImageRecord) -> None:
        if record.url in self._known_urls:
            return
        self._known_urls.add(record.url)
        self._records.append(record)
        await asyncio.to_thread(self._persist)

    def _persist(self) -> None:
        payload = [r.to_dict() for r in self._records]
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._records[-limit:]][::-1]


class DerpiClient:
    def __init__(self, token: str, settings_manager: SettingsManager):
        self._token = token
        self._settings_manager = settings_manager
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            connector = aiohttp.TCPConnector(limit=32)
            self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def fetch_random_image(
        self, tags: List[str], *, skip_urls: Optional[Set[str]] = None
    ) -> Optional[ImageRecord]:
        if not self._session:
            raise RuntimeError("HTTP session not initialized")

        params: Dict[str, Any] = {
            "q": " ".join(tags),
            "per_page": 50,
            "page": 1,
            "key": self._token,
        }
        if self._settings_manager.settings.filter_id:
            params["filter_id"] = self._settings_manager.settings.filter_id

        skip_urls = skip_urls or set()
        backoff = 1
        while True:
            try:
                async with self._session.get(DERPI_SEARCH_URL, params=params) as resp:
                    if resp.status == 200:
                        payload = await resp.json()
                        images = payload.get("images", [])
                        random.shuffle(images)
                        for img in images:
                            representations = img.get("representations", {})
                            url = (
                                representations.get("large")
                                or representations.get("full")
                                or representations.get("medium")
                            )
                            if not url or url in skip_urls:
                                continue

                            return ImageRecord(
                                url=url,
                                author=img.get("uploader"),
                                source=img.get("view_url"),
                                tags=img.get("tags", []),
                                posted_at=_now_iso(),
                            )

                        logger.info("No fresh images for tags: %s", tags)
                        return None

                    if resp.status in {500, 502, 503, 504}:
                        logger.warning(
                            "Derpibooru temporary error %s, retrying in %ss",
                            resp.status,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 900)
                        continue

                    logger.error("Derpibooru returned %s for tags %s", resp.status, tags)
                    return None

            except aiohttp.ClientError as exc:
                logger.warning("Network error talking to Derpibooru: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 900)


class AutoPoster:
    def __init__(
        self,
        bot: Bot,
        derpi_client: DerpiClient,
        store: SentImageStore,
        settings_manager: SettingsManager,
    ):
        self._bot = bot
        self._derpi = derpi_client
        self._store = store
        self._settings = settings_manager
        self._queue: asyncio.Queue[Optional[List[str]]] = asyncio.Queue()
        self._stop_event = asyncio.Event()
        self._interval_event = asyncio.Event()
        self._worker: Optional[asyncio.Task] = None
        self._scheduler: Optional[asyncio.Task] = None
        self.next_run_at: Optional[datetime] = None

    async def start(self) -> None:
        self._worker = asyncio.create_task(self._post_loop(), name="post-loop")
        self._scheduler = asyncio.create_task(
            self._scheduler_loop(), name="scheduler-loop"
        )
        await self.post_now()

    async def stop(self) -> None:
        self._stop_event.set()
        self._interval_event.set()
        await self._queue.put(None)

        for task in (self._worker, self._scheduler):
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    def notify_settings_changed(self) -> None:
        self._interval_event.set()

    async def post_now(self, tags: Optional[List[str]] = None) -> None:
        await self._queue.put(tags)

    async def _scheduler_loop(self) -> None:
        while not self._stop_event.is_set():
            interval_minutes = max(1, self._settings.settings.post_interval_minutes)
            self.next_run_at = datetime.now(timezone.utc) + timedelta(
                minutes=interval_minutes
            )
            wait_seconds = max(
                1, (self.next_run_at - datetime.now(timezone.utc)).total_seconds()
            )

            try:
                await asyncio.wait_for(
                    self._interval_event.wait(), timeout=wait_seconds
                )
                self._interval_event.clear()
                continue
            except asyncio.TimeoutError:
                await self._queue.put(None)

    async def _post_loop(self) -> None:
        while not self._stop_event.is_set():
            tags = await self._queue.get()
            if self._stop_event.is_set():
                break
            try:
                await self._post(tags)
            except Exception as exc:
                logger.exception("Unhandled error while posting: %s", exc)

    async def _post(self, tags: Optional[List[str]]) -> bool:
        chosen_tags = tags or self._settings.settings.pick_random_tags()
        record = await self._derpi.fetch_random_image(
            chosen_tags, skip_urls=self._store.known_urls
        )
        if not record:
            logger.info("No image was sent (tags: %s)", chosen_tags)
            return False

        caption_parts = []
        if record.author:
            caption_parts.append(f"Автор: {record.author}")
        if record.source:
            caption_parts.append(f"Источник: {record.source}")
        if record.tags:
            caption_parts.append(f"Теги: {', '.join(record.tags[:20])}")
        caption = "\n".join(caption_parts) or None

        try:
            await self._bot.send_photo(chat_id=CHANNEL_ID, photo=record.url, caption=caption)
            await self._store.add(record)
            logger.info("Sent image: %s", record.url)
            return True
        except Exception as exc:  # pragma: no cover - depends on telegram runtime
            logger.error("Failed to send image to Telegram: %s", exc)
            return False


async def command_listener(
    autoposter: AutoPoster, settings_manager: SettingsManager
) -> None:
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        cmd = line.strip()
        if not cmd:
            continue

        if cmd.lower() in {"postnow", ">> postnow"}:
            logger.info("Manual post requested from CLI")
            await autoposter.post_now()
        elif cmd.lower().startswith("posttags "):
            tags_input = cmd[len("posttags ") :]
            tags_override = parse_tag_lines(tags_input)
            await autoposter.post_now(tags_override[0] if tags_override else None)
        elif cmd.lower().startswith("timetopost"):
            if autoposter.next_run_at:
                delta = autoposter.next_run_at - datetime.now(timezone.utc)
                logger.info("Next scheduled post in %.0f seconds", delta.total_seconds())
            else:
                logger.info("Scheduler has not been initialized yet")
        elif cmd.lower().startswith("setinterval "):
            try:
                interval_value = int(cmd.split()[1])
                await settings_manager.update(interval=interval_value)
                autoposter.notify_settings_changed()
                logger.info("Interval updated to %s minutes", interval_value)
            except (ValueError, IndexError):
                logger.info("Usage: setinterval <minutes>")
        else:
            logger.info("Unknown command: %s", cmd)


INDEX_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Derpibooru Bot Dashboard</title>
  <style>
    :root {
      --bg: #0f172a;
      --card: rgba(255, 255, 255, 0.06);
      --border: rgba(255, 255, 255, 0.08);
      --text: #e2e8f0;
      --muted: #94a3b8;
      --accent: #22d3ee;
      --accent-2: #f97316;
      --shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Manrope", "Fira Sans", system-ui, -apple-system, sans-serif;
      background: radial-gradient(140% 120% at 20% 20%, rgba(34, 211, 238, 0.2), transparent 40%),
                  radial-gradient(100% 100% at 80% 0%, rgba(249, 115, 22, 0.18), transparent 35%),
                  var(--bg);
      color: var(--text);
      min-height: 100vh;
      padding: 32px 20px 60px;
    }

    .page {
      max-width: 1200px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }

    header {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 12px;
    }

    .eyebrow {
      letter-spacing: 0.1em;
      font-size: 12px;
      text-transform: uppercase;
      color: var(--accent);
      margin: 0 0 6px;
    }

    h1 {
      margin: 0;
      font-size: 32px;
    }

    .muted { color: var(--muted); margin: 4px 0 0; }

    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 18px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(6px);
    }

    .layout {
      display: grid;
      grid-template-columns: 360px 1fr;
      gap: 16px;
    }

    .card-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }

    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.08);
      color: var(--text);
      font-size: 12px;
    }

    label {
      display: block;
      margin: 12px 0 6px;
      font-weight: 600;
    }

    input, textarea {
      width: 100%;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 14px;
      outline: none;
      transition: border 0.2s ease, box-shadow 0.2s ease;
    }

    input:focus, textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(34, 211, 238, 0.25);
    }

    textarea { min-height: 110px; resize: vertical; }

    button {
      background: linear-gradient(120deg, var(--accent), var(--accent-2));
      color: #0b1220;
      border: none;
      border-radius: 12px;
      padding: 12px 16px;
      font-weight: 700;
      cursor: pointer;
      transition: transform 0.15s ease, box-shadow 0.15s ease;
      box-shadow: 0 10px 30px rgba(34, 211, 238, 0.2);
    }

    button.secondary {
      background: rgba(255, 255, 255, 0.08);
      color: var(--text);
      box-shadow: none;
    }

    button:hover { transform: translateY(-1px); }
    button:active { transform: translateY(0); }

    .actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 12px;
    }

    .image-card {
      position: relative;
      overflow: hidden;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.04);
      min-height: 200px;
      display: flex;
      flex-direction: column;
    }

    .image-card img {
      width: 100%;
      height: 180px;
      object-fit: cover;
      background: #0b1220;
    }

    .image-info {
      padding: 10px 12px 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .tag-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .badge {
      padding: 4px 8px;
      border-radius: 999px;
      background: rgba(34, 211, 238, 0.1);
      color: var(--text);
      font-size: 12px;
      border: 1px solid rgba(255, 255, 255, 0.08);
    }

    .empty {
      text-align: center;
      color: var(--muted);
      padding: 20px;
    }

    @media (max-width: 980px) {
      .layout { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="page">
    <header>
      <div>
        <p class="eyebrow">Derpibooru Bot</p>
        <h1>Галерея и настройки</h1>
        <p class="muted">Смотрите уже отправленные изображения и меняйте теги/частоту прямо из браузера.</p>
      </div>
      <div class="actions">
        <button id="post-now">Отправить сейчас</button>
        <button class="secondary" id="reload-images">Обновить галерею</button>
      </div>
    </header>

    <section class="layout">
      <article class="card settings">
        <div class="card-header">
          <div>
            <h2 style="margin:0;">Настройки постинга</h2>
            <p class="muted">Каждая строка — группа тегов, внутри строки теги разделяйте пробелом или запятой.</p>
          </div>
          <div class="chip" id="next-run-chip">Загрузка...</div>
        </div>
        <form id="settings-form">
          <label for="interval">Интервал (минуты)</label>
          <input type="number" min="1" id="interval" name="interval" required />

          <label for="filterId">Filter ID (Derpibooru)</label>
          <input type="number" id="filterId" name="filterId" placeholder="56027" />

          <label for="tags">Группы тегов</label>
          <textarea id="tags" name="tags" placeholder="pony, solo&#10;safe, smiling"></textarea>

          <div class="actions" style="justify-content: flex-start; margin-top: 12px;">
            <button type="submit">Сохранить</button>
            <button type="button" class="secondary" id="refresh-settings">Сбросить</button>
          </div>
        </form>
      </article>

      <article class="card gallery">
        <div class="card-header">
          <div>
            <h2 style="margin:0;">Полученные картинки</h2>
            <p class="muted">Последние изображения, которые уже ушли в канал.</p>
          </div>
          <div class="chip" id="images-count">0</div>
        </div>
        <div id="grid" class="grid"></div>
        <div id="empty-state" class="empty" style="display:none;">Пока нет данных</div>
      </article>
    </section>
  </div>

  <script>
    const grid = document.getElementById('grid');
    const emptyState = document.getElementById('empty-state');
    const imagesCount = document.getElementById('images-count');
    const intervalInput = document.getElementById('interval');
    const filterInput = document.getElementById('filterId');
    const tagsInput = document.getElementById('tags');
    const nextRunChip = document.getElementById('next-run-chip');

    function formatDate(dateString) {
      if (!dateString) return '—';
      const d = new Date(dateString);
      return d.toLocaleString();
    }

    function renderImages(images) {
      if (!images || images.length === 0) {
        grid.innerHTML = '';
        emptyState.style.display = 'block';
        imagesCount.textContent = '0';
        return;
      }
      emptyState.style.display = 'none';
      imagesCount.textContent = images.length;
      grid.innerHTML = images.map((img) => {
        const tags = (img.tags || []).slice(0, 6).map(t => `<span class="badge">${t}</span>`).join('');
        const link = img.source || img.url;
        return `
          <article class="image-card">
            <a href="${link}" target="_blank" rel="noopener noreferrer" style="display:block;">
              <img src="${img.url}" alt="img" loading="lazy" />
            </a>
            <div class="image-info">
              <div class="muted">${formatDate(img.posted_at)}</div>
              <div class="muted">${img.author ? 'Автор: ' + img.author : ''}</div>
              <div class="tag-row">${tags}</div>
            </div>
          </article>
        `;
      }).join('');
    }

    async function loadImages() {
      const res = await fetch('/api/images?limit=120');
      const data = await res.json();
      renderImages(data.images || []);
    }

    function tagsToTextarea(tags) {
      return (tags || []).map(group => (group || []).join(', ')).join('\\n');
    }

    function updateNextRun(nextRun) {
      if (!nextRun) {
        nextRunChip.textContent = 'Ожидание расписания';
        return;
      }
      nextRunChip.textContent = 'Следующий пост: ' + formatDate(nextRun);
    }

    async function loadSettings() {
      const res = await fetch('/api/settings');
      const data = await res.json();
      intervalInput.value = data.post_interval_minutes || 60;
      filterInput.value = data.filter_id ?? '';
      tagsInput.value = tagsToTextarea(data.tags);
      updateNextRun(data.next_run_at);
    }

    async function saveSettings(evt) {
      evt.preventDefault();
      const payload = {
        post_interval_minutes: Number(intervalInput.value),
        filter_id: filterInput.value ? Number(filterInput.value) : null,
        tags_raw: tagsInput.value || ''
      };
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      await loadSettings();
    }

    async function postNow() {
      await fetch('/api/post-now', { method: 'POST' });
    }

    document.getElementById('settings-form').addEventListener('submit', saveSettings);
    document.getElementById('post-now').addEventListener('click', postNow);
    document.getElementById('reload-images').addEventListener('click', loadImages);
    document.getElementById('refresh-settings').addEventListener('click', loadSettings);

    loadSettings();
    loadImages();
    setInterval(loadImages, 60000);
  </script>
</body>
</html>
"""


def create_web_app(
    store: SentImageStore, settings_manager: SettingsManager, autoposter: AutoPoster
) -> web.Application:
    app = web.Application()
    app["store"] = store
    app["settings"] = settings_manager
    app["autoposter"] = autoposter

    async def index(request: web.Request) -> web.Response:
        return web.Response(text=INDEX_HTML, content_type="text/html")

    async def get_images(request: web.Request) -> web.Response:
        try:
            limit = min(
                MAX_IMAGES_EXPOSE,
                max(1, int(request.query.get("limit", 100))),
            )
        except ValueError:
            limit = 100
        images = store.get_recent(limit)
        return web.json_response({"images": images})

    async def get_settings(request: web.Request) -> web.Response:
        data = settings_manager.settings.to_dict()
        data["next_run_at"] = (
            autoposter.next_run_at.isoformat() if autoposter.next_run_at else None
        )
        data["tags_text"] = settings_manager.settings.tags_text()
        return web.json_response(data)

    async def update_settings(request: web.Request) -> web.Response:
        payload = await request.json()
        interval_raw = payload.get("post_interval_minutes")
        try:
            interval = int(interval_raw) if interval_raw is not None else None
        except (TypeError, ValueError):
            interval = None

        filter_raw = payload.get("filter_id")
        try:
            filter_id = int(filter_raw) if filter_raw not in (None, "") else None
        except (TypeError, ValueError):
            filter_id = None

        tags_raw = payload.get("tags_raw") or payload.get("tagsText") or ""
        await settings_manager.update(
            tags_raw=tags_raw, interval=interval, filter_id=filter_id
        )
        autoposter.notify_settings_changed()

        data = settings_manager.settings.to_dict()
        data["next_run_at"] = (
            autoposter.next_run_at.isoformat() if autoposter.next_run_at else None
        )
        return web.json_response({"ok": True, "settings": data})

    async def post_now(request: web.Request) -> web.Response:
        payload = {}
        if request.can_read_body:
            with suppress(json.JSONDecodeError):
                payload = await request.json()
        tags_raw = payload.get("tags_raw") if isinstance(payload, dict) else None
        tags_override = parse_tag_lines(tags_raw or "") if tags_raw else None
        await autoposter.post_now(tags_override[0] if tags_override else None)
        return web.json_response({"ok": True})

    app.router.add_get("/", index)
    app.router.add_get("/api/images", get_images)
    app.router.add_get("/api/settings", get_settings)
    app.router.add_post("/api/settings", update_settings)
    app.router.add_post("/api/post-now", post_now)
    return app


async def main() -> None:
    settings_manager = SettingsManager(SETTINGS_FILE)
    await settings_manager.load()

    store = SentImageStore(SENT_IMAGES_FILE)
    derpi_client = DerpiClient(DERPIBOORU_TOKEN, settings_manager)
    await derpi_client.start()

    bot = Bot(token=TELEGRAM_TOKEN)
    autoposter = AutoPoster(bot, derpi_client, store, settings_manager)
    await autoposter.start()

    web_app = create_web_app(store, settings_manager, autoposter)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, host=WEB_HOST, port=WEB_PORT)
    await site.start()
    logger.info("Dashboard available at http://%s:%s", WEB_HOST, WEB_PORT)

    listener = asyncio.create_task(
        command_listener(autoposter, settings_manager), name="stdin-listener"
    )

    try:
        await listener
    except asyncio.CancelledError:
        pass
    finally:
        await autoposter.stop()
        await derpi_client.close()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
