"""Runtime settings. No LLM or scraping API credentials are required here."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default="", repr=False)
    worker_interval: float = 60
    enabled: bool = True
    article_max_pages: str = "1"

    def __post_init__(self) -> None:
        if not math.isfinite(self.worker_interval) or self.worker_interval <= 0:
            raise ValueError("WORKER_INTERVAL must be a finite number greater than zero")
        if not isinstance(self.article_max_pages, str):
            raise ValueError("CONNECTOR_ARTICLE_MAX_PAGES must be a string")

    @classmethod
    def from_env(cls, mapping: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if mapping is None else mapping
        try:
            interval = float(env.get("WORKER_INTERVAL", "60"))
        except (ValueError, TypeError) as exc:
            raise ValueError("WORKER_INTERVAL must be a number greater than zero") from exc
        return cls(
            database_url=env.get("DATABASE_URL", ""),
            worker_interval=interval,
            enabled=env.get("SOCIAL_COLLECTION_ENABLED", "true").strip().lower() in TRUE_VALUES,
            article_max_pages=env.get("CONNECTOR_ARTICLE_MAX_PAGES", "1"),
        )
