"""URL изображений Wildberries.

Картинки WB лежат на basket-серверах CDN. Хост определяется по «тому»
(vol = nm // 100000): WB распределяет диапазоны томов по basket-01..NN.
Схема периодически расширяется (добавляются новые basket-серверы), поэтому
resolve() проверяет вычисленный хост и при 404 сканирует остальные.
"""

from __future__ import annotations

import requests

_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.wildberries.ru/"}

# (верхняя граница тома, номер basket-сервера)
_RANGES = [
    (143, "01"), (287, "02"), (431, "03"), (719, "04"), (1007, "05"),
    (1061, "06"), (1115, "07"), (1169, "08"), (1313, "09"), (1601, "10"),
    (1655, "11"), (1919, "12"), (2045, "13"), (2189, "14"), (2405, "15"),
    (2621, "16"), (2837, "17"), (3053, "18"), (3269, "19"), (3485, "20"),
    (3701, "21"), (3917, "22"), (4877, "23"), (5437, "24"), (5687, "25"),
    (6707, "26"), (7053, "27"), (7849, "28"), (8403, "29"), (9229, "30"),
]
_MAX_BASKET = 31


def _basket(vol: int) -> str:
    for hi, b in _RANGES:
        if vol <= hi:
            return b
    return str(_MAX_BASKET)


def image_url(nm: int | str, basket: str | None = None) -> str:
    """Вычислить URL основной картинки (без проверки сети)."""
    nm = int(nm)
    vol = nm // 100000
    part = nm // 1000
    b = basket or _basket(vol)
    return f"https://basket-{b}.wbbasket.ru/vol{vol}/part{part}/{nm}/images/big/1.webp"


def resolve(nm: int | str, timeout: float = 8.0) -> str:
    """Вернуть рабочий URL картинки (с проверкой) или '' если не найден."""
    nm = int(nm)
    vol = nm // 100000
    candidates = [_basket(vol)]
    # Фолбэк: перебрать остальные basket-серверы, если основной не отдал.
    candidates += [f"{i:02d}" for i in range(1, _MAX_BASKET + 1)
                   if f"{i:02d}" != candidates[0]]
    for b in candidates:
        url = image_url(nm, basket=b)
        try:
            r = requests.get(url, headers=_HEADERS, stream=True, timeout=timeout)
            r.close()
            if r.status_code == 200:
                return url
        except requests.RequestException:
            continue
    return ""
