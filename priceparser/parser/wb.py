"""Парсер Wildberries через внутренний JSON-API (без браузера).

WB — это SPA, цены подгружаются с card.wb.ru. Этот публичный эндпоинт
отдаёт карточку товара в JSON, что быстрее и стабильнее, чем Selenium.
"""

from __future__ import annotations

import re

import requests

from .base import Parser, Product

# Публичный эндпоинт карточки. dest — регион доставки (определяет цену/наличие).
# Актуальная версия — v4: цена лежит в products[].sizes[].price (в копейках).
_CARD_API = "https://card.wb.ru/cards/v4/detail"
_DEFAULT_PARAMS = {
    "appType": "1",
    "curr": "rub",
    "dest": "-1257786",  # Москва; меняет региональную цену/наличие
    "spp": "30",
}
_SKU_RE = re.compile(r"/catalog/(\d+)")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
    # WB-API отдаёт данные только с фирменным Origin/Referer.
    "Origin": "https://www.wildberries.ru",
    "Referer": "https://www.wildberries.ru/",
}


class WildberriesParser(Parser):
    marketplace = "wb"

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def extract_sku(self, url_or_sku: str) -> str:
        s = url_or_sku.strip()
        if s.isdigit():
            return s
        m = _SKU_RE.search(s)
        if not m:
            raise ValueError(f"Не удалось извлечь артикул WB из: {url_or_sku!r}")
        return m.group(1)

    def parse(self, url_or_sku: str) -> Product:
        sku = self.extract_sku(url_or_sku)
        params = {**_DEFAULT_PARAMS, "nm": sku}
        resp = self.session.get(_CARD_API, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        # v4 кладёт товары на верхний уровень; старые версии — в data.products.
        products = (data.get("data") or {}).get("products") or data.get("products") or []
        if not products:
            raise LookupError(f"Товар WB {sku} не найден (пустой ответ API)")
        p = products[0]

        title = p.get("name", "").strip() or f"Товар {sku}"
        price = self._extract_price(p)
        in_stock = price is not None and self._has_stock(p)

        from ._wb_images import resolve as resolve_image

        return Product(
            sku=sku,
            title=title,
            price=(price or 0.0),
            url=f"https://www.wildberries.ru/catalog/{sku}/detail.aspx",
            in_stock=in_stock,
            image_url=resolve_image(sku),
        )

    @staticmethod
    def _extract_price(p: dict) -> float | None:
        """Цена приходит в копейках внутри sizes[].price.product."""
        for size in p.get("sizes") or []:
            price_obj = size.get("price") or {}
            # product — итоговая цена с СПП; total/basic — запасные варианты
            kopecks = (
                price_obj.get("product")
                or price_obj.get("total")
                or price_obj.get("basic")
            )
            if kopecks:
                return round(kopecks / 100, 2)
        # Старый формат: цена прямо в продукте (в рублях).
        if p.get("salePriceU"):
            return round(p["salePriceU"] / 100, 2)
        return None

    @staticmethod
    def _has_stock(p: dict) -> bool:
        for size in p.get("sizes") or []:
            for stock in size.get("stocks") or []:
                if stock.get("qty", 0) > 0:
                    return True
        # Если поля stocks нет, но цена есть — считаем доступным.
        return not any("stocks" in (s or {}) for s in (p.get("sizes") or []))
