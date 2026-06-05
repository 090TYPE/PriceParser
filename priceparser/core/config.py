"""Конфигурация из переменных окружения / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    telegram_token: str | None
    telegram_chat_id: str | None
    check_interval: int
    price_drop_threshold: float
    db_path: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
            check_interval=int(os.getenv("CHECK_INTERVAL", "3600")),
            price_drop_threshold=float(os.getenv("PRICE_DROP_THRESHOLD", "0.0")),
            db_path=os.getenv("DB_PATH", "priceparser.db"),
        )

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)
