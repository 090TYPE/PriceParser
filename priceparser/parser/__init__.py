"""Парсеры маркетплейсов."""

from .base import Parser, Product
from .wb import WildberriesParser

# Реестр маркетплейс -> класс парсера.
PARSERS = {
    "wb": WildberriesParser,
}


def get_parser(marketplace: str) -> Parser:
    """Вернуть экземпляр парсера для маркетплейса ('wb', 'ozon', 'yandex')."""
    marketplace = marketplace.lower()
    # Ленивый импорт: Selenium тяжёлый и нужен только для Ozon/Яндекса.
    if marketplace == "ozon":
        from .ozon import OzonParser

        return OzonParser()
    if marketplace == "yandex":
        from .yandex import YandexMarketParser

        return YandexMarketParser()
    try:
        return PARSERS[marketplace]()
    except KeyError as exc:
        raise ValueError(f"Неизвестный маркетплейс: {marketplace!r}") from exc


def detect_marketplace(url: str) -> str:
    """Определить маркетплейс по URL."""
    u = url.lower()
    if "wildberries" in u or "wb.ru" in u:
        return "wb"
    if "ozon" in u:
        return "ozon"
    if "market.yandex" in u or "ya.cc" in u:
        return "yandex"
    raise ValueError(f"Не удалось определить маркетплейс по URL: {url}")
