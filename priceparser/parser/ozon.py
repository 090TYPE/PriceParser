"""Парсер Ozon через Selenium.

Ozon агрессивно защищён от ботов и рендерит цену через JS, поэтому здесь
оправдан полноценный браузер. Используем undetected-chromedriver, чтобы
снизить шанс блокировки, и ждём появления элемента с ценой.

Зависимости (ставятся отдельно):
    pip install selenium undetected-chromedriver
"""

from __future__ import annotations

import re
import time

from .base import Parser, Product

_SKU_RE = re.compile(r"/product/[^/]*?-(\d+)/?")
# Селекторы Ozon меняются; держим несколько кандидатов для цены.
_PRICE_SELECTORS = [
    "[data-widget='webPrice']",
    "span[class*='tsHeadline']",
]


class OzonParser(Parser):
    marketplace = "ozon"

    def __init__(self, headless: bool = True, wait: float = 12.0) -> None:
        self.headless = headless
        self.wait = wait
        self._driver = None

    # ---- драйвер (ленивая инициализация) --------------------------------
    def _ensure_driver(self):
        if self._driver is not None:
            return self._driver
        from ._browser import make_driver

        self._driver = make_driver(self.headless)
        return self._driver

    def extract_sku(self, url_or_sku: str) -> str:
        s = url_or_sku.strip()
        if s.isdigit():
            return s
        m = _SKU_RE.search(s)
        if not m:
            raise ValueError(f"Не удалось извлечь артикул Ozon из: {url_or_sku!r}")
        return m.group(1)

    def parse(self, url_or_sku: str) -> Product:
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
        from bs4 import BeautifulSoup

        sku = self.extract_sku(url_or_sku)
        url = url_or_sku if url_or_sku.startswith("http") else (
            f"https://www.ozon.ru/product/{sku}/"
        )

        driver = self._ensure_driver()
        driver.get(url)

        # Подождать появления любого из кандидатов цены.
        try:
            WebDriverWait(driver, self.wait).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, _PRICE_SELECTORS[0])
                )
            )
        except TimeoutException:
            time.sleep(2)  # дать догрузиться / возможная капча

        soup = BeautifulSoup(driver.page_source, "html.parser")
        title = self._extract_title(soup, sku)
        from ._browser import raise_if_blocked

        raise_if_blocked(title, "Ozon")
        price = self._extract_price(soup)

        return Product(
            sku=sku,
            title=title,
            price=(price or 0.0),
            url=url,
            in_stock=price is not None,
            image_url=self._extract_image(soup),
        )

    @staticmethod
    def _extract_image(soup) -> str:
        og = soup.find("meta", property="og:image")
        return og["content"] if og and og.get("content") else ""

    @staticmethod
    def _extract_title(soup, sku: str) -> str:
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            return h1.get_text(strip=True)
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        return f"Товар {sku}"

    @staticmethod
    def _extract_price(soup) -> float | None:
        widget = soup.select_one("[data-widget='webPrice']")
        text = widget.get_text(" ", strip=True) if widget else ""
        if not text:
            for sel in _PRICE_SELECTORS[1:]:
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(" ", strip=True)
                    break
        # Первое число с символом рубля: "1 299 ₽" -> 1299
        m = re.search(r"(\d[\d\s ]*)\s*₽", text)
        if not m:
            return None
        digits = re.sub(r"[\s ]", "", m.group(1))
        return float(digits) if digits else None

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            finally:
                self._driver = None
