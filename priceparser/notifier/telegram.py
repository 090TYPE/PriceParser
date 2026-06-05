"""Уведомления. Telegram через простой HTTP Bot API (без async-зависимостей)."""

from __future__ import annotations

from abc import ABC, abstractmethod

import requests


class Notifier(ABC):
    @abstractmethod
    def notify(self, text: str) -> None:
        ...


class ConsoleNotifier(Notifier):
    """Запасной канал — печать в консоль (когда Telegram не настроен)."""

    def notify(self, text: str) -> None:
        print(f"[NOTIFY] {text}")


class TelegramNotifier(Notifier):
    def __init__(self, token: str, chat_id: str, timeout: float = 10.0) -> None:
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout
        self._api = f"https://api.telegram.org/bot{token}/sendMessage"

    def notify(self, text: str) -> None:
        resp = requests.post(
            self._api,
            json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()


def build_notifier(config) -> Notifier:
    """Создать Telegram-нотификатор, если настроен, иначе консольный."""
    if config.telegram_enabled:
        return TelegramNotifier(config.telegram_token, config.telegram_chat_id)
    return ConsoleNotifier()
