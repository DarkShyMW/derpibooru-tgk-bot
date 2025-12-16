from __future__ import annotations
import aiohttp
import asyncio
import random
from typing import Any, Dict, List, Optional, Set
from app.models import ImageRecord, now_iso


class DerpiClient:
    def __init__(self, *, token: str, search_url: str, filter_id: int, http_pool_limit: int):
        self._token = token
        self._search_url = search_url
        self._filter_id = filter_id
        self._http_pool_limit = http_pool_limit
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session:
            return
        connector = aiohttp.TCPConnector(
            limit=self._http_pool_limit,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
            keepalive_timeout=30,
        )
        timeout = aiohttp.ClientTimeout(total=20)
        self._session = aiohttp.ClientSession(connector=connector, timeout=timeout)

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def fetch_random_image(self, tags: List[str], *, skip_urls: Set[str]) -> Optional[ImageRecord]:
        if not self._session:
            raise RuntimeError("DerpiClient not started")

        params: Dict[str, Any] = {
            "q": " ".join(tags),
            "per_page": 50,
            "page": 1,
            "key": self._token,
            "filter_id": self._filter_id,
        }

        backoff = 1
        for _ in range(6):
            try:
                async with self._session.get(self._search_url, params=params) as resp:
                    if resp.status == 200:
                        payload = await resp.json()
                        images = payload.get("images", [])
                        random.shuffle(images)
                        for img in images:
                            reps = img.get("representations", {}) or {}
                            url = reps.get("large") or reps.get("full") or reps.get("medium")
                            if not url or url in skip_urls:
                                continue
                            return ImageRecord(
                                url=url,
                                author=img.get("uploader"),
                                source=img.get("view_url"),
                                tags=img.get("tags", []) or [],
                                posted_at=now_iso(),
                            )
                        return None

                    if resp.status in (429, 500, 502, 503, 504):
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 30)
                        continue

                    return None

            except aiohttp.ClientError:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

        return None
