from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ImageRecord:
    url: str
    author: Optional[str]
    source: Optional[str]
    tags: List[str]
    posted_at: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
