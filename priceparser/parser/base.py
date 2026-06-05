"""Базовые абстракции парсеров."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Product:
    """Снимок состояния товара на момент проверки."""

    sku: str  # артикул на маркетплейсе
    title: str
    price: float  # текущая цена с учётом скидки, в рублях
    url: str
    in_stock: bool = True
    currency: str = "RUB"
    image_url: str = ""  # ссылка на картинку товара (если удалось определить)

    def __str__(self) -> str:
        stock = "" if self.in_stock else " (нет в наличии)"
        return f"{self.title} — {self.price:.0f} {self.currency}{stock}"


class Parser(ABC):
    """Интерфейс парсера маркетплейса."""

    #: короткий код маркетплейса, напр. 'wb'
    marketplace: str = ""

    @abstractmethod
    def parse(self, url_or_sku: str) -> Product:
        """Получить актуальное состояние товара по ссылке или артикулу."""

    @abstractmethod
    def extract_sku(self, url_or_sku: str) -> str:
        """Извлечь артикул из ссылки (или вернуть как есть, если это артикул)."""

    def close(self) -> None:
        """Освободить ресурсы (драйвер браузера и т.п.). По умолчанию ничего."""
