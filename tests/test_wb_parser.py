"""Офлайн-тесты парсинга WB (без сети) и логики уведомлений."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from priceparser.parser.wb import WildberriesParser
from priceparser.parser import detect_marketplace


def test_extract_sku_from_url():
    p = WildberriesParser()
    assert p.extract_sku("https://www.wildberries.ru/catalog/68767845/detail.aspx") == "68767845"
    assert p.extract_sku("12345") == "12345"


def test_detect_marketplace():
    assert detect_marketplace("https://www.wildberries.ru/catalog/1/detail.aspx") == "wb"
    assert detect_marketplace("https://www.ozon.ru/product/x-1/") == "ozon"
    assert detect_marketplace("https://market.yandex.ru/product--slug/679402099") == "yandex"


def test_yandex_extract_sku():
    # Импорт здесь, чтобы тест не требовал установленного selenium на уровне модуля.
    from priceparser.parser.yandex import YandexMarketParser

    p = YandexMarketParser()
    assert p.extract_sku("https://market.yandex.ru/product--slug/679402099?sku=1") == "679402099"
    assert p.extract_sku("https://market.yandex.ru/product/123456") == "123456"
    assert p.extract_sku("987654") == "987654"


def test_price_extraction_kopecks():
    # Формат v4: цена в копейках под sizes[].price.product
    product = {
        "name": "Тест",
        "sizes": [{"price": {"basic": 405000, "product": 293600},
                   "stocks": [{"qty": 3}]}],
    }
    assert WildberriesParser._extract_price(product) == 2936.0
    assert WildberriesParser._has_stock(product) is True


def test_out_of_stock():
    product = {"name": "Нет", "sizes": [{"price": {}, "stocks": []}]}
    assert WildberriesParser._extract_price(product) is None
    assert WildberriesParser._has_stock(product) is False


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
