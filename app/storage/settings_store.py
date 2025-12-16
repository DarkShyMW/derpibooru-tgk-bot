from __future__ import annotations
import asyncio
import json
import random
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_TAG_GROUPS = [["penis"], ["anal"], ["female"], ["vulva"], ["creampie"]]


def parse_tag_lines(raw_text: str) -> List[List[str]]:
    groups: List[List[str]] = []
    for line in (raw_text or "").splitlines():
        parts = [p.strip() for p in re.split(r"[ ,]+", line) if p.strip()]
        if parts:
            groups.append(parts)
    return groups


@dataclass
class Settings:
    tags: List[List[str]]
    post_interval_minutes: int
    filter_id: Optional[int]

    @classmethod
    def from_dict(cls, data: Dict[str, Any], *, fallback_interval: int, fallback_filter: int) -> "Settings":
        tags_raw = data.get("tags") or DEFAULT_TAG_GROUPS
        tags: List[List[str]] = []
        for g in tags_raw:
            if isinstance(g, str):
                gg = parse_tag_lines(g)
                if gg:
                    tags.append(gg[0])
            elif isinstance(g, list):
                gg = [str(x).strip() for x in g if str(x).strip()]
                if gg:
                    tags.append(gg)

        if not tags:
            tags = DEFAULT_TAG_GROUPS

        try:
            interval = max(1, int(data.get("post_interval_minutes", fallback_interval)))
        except Exception:
            interval = fallback_interval

        fid_raw = data.get("filter_id", fallback_filter)
        try:
            filter_id = int(fid_raw) if fid_raw is not None else None
        except Exception:
            filter_id = fallback_filter

        return cls(tags=tags, post_interval_minutes=interval, filter_id=filter_id)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def tags_text(self) -> str:
        return "\n".join(", ".join(g) for g in self.tags)

    def pick_random_tags(self) -> List[str]:
        return random.choice(self.tags) if self.tags else []


class SettingsStore:
    def __init__(self, path: Path, *, default_interval: int, default_filter_id: int):
        self._path = path
        self._lock = asyncio.Lock()
        self.default_interval = default_interval
        self.default_filter_id = default_filter_id
        self.settings = Settings(tags=DEFAULT_TAG_GROUPS, post_interval_minutes=default_interval, filter_id=default_filter_id)

    async def load(self) -> Settings:
        if not self._path.exists():
            await self.save()
            return self.settings

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self.settings = Settings.from_dict(
                    raw,
                    fallback_interval=self.default_interval,
                    fallback_filter=self.default_filter_id,
                )
        except Exception:
            await self.save()

        return self.settings

    async def save(self) -> None:
        async with self._lock:
            self._path.write_text(
                json.dumps(self.settings.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    async def update(self, *, tags_raw: Optional[str], interval: Optional[int], filter_id: Optional[int]) -> Settings:
        if tags_raw is not None:
            parsed = parse_tag_lines(tags_raw)
            if parsed:
                self.settings.tags = parsed

        if interval is not None:
            self.settings.post_interval_minutes = max(1, int(interval))

        self.settings.filter_id = filter_id

        await self.save()
        return self.settings
