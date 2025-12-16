from __future__ import annotations
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Set
from app.models import ImageRecord


class SentImageStore:
    def __init__(self, path: Path):
        self._path = path
        self._lock = asyncio.Lock()
        self._records: List[ImageRecord] = []
        self._known: Set[str] = set()
        self._load_sync()

    def _load_sync(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return

        if not isinstance(raw, list):
            return

        for item in raw:
            if isinstance(item, dict) and item.get("url"):
                r = ImageRecord(
                    url=item["url"],
                    author=item.get("author"),
                    source=item.get("source"),
                    tags=item.get("tags", []) or [],
                    posted_at=item.get("posted_at"),
                )
                if r.url not in self._known:
                    self._known.add(r.url)
                    self._records.append(r)

    @property
    def known_urls(self) -> Set[str]:
        return self._known

    async def add(self, record: ImageRecord) -> None:
        if record.url in self._known:
            return
        self._known.add(record.url)
        self._records.append(record)
        await asyncio.to_thread(self._persist_sync)

    def _persist_sync(self) -> None:
        payload = [r.to_dict() for r in self._records]
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def recent(self, limit: int) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._records[-limit:]][::-1]
