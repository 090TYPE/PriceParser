"""Логика проверки цен и уведомлений."""

from __future__ import annotations

import logging

from ..notifier import Notifier
from ..parser import get_parser
from ..storage import Database

log = logging.getLogger("priceparser.tracker")


class Tracker:
    def __init__(self, db: Database, notifier: Notifier, drop_threshold: float = 0.0):
        self.db = db
        self.notifier = notifier
        self.drop_threshold = drop_threshold
        self._parsers: dict[str, object] = {}

    def _parser_for(self, marketplace: str):
        if marketplace not in self._parsers:
            self._parsers[marketplace] = get_parser(marketplace)
        return self._parsers[marketplace]

    def check_all(self) -> None:
        """Проверить все товары; один сбой не должен ронять цикл."""
        products = self.db.list_products()
        log.info("Проверяю %d товар(ов)", len(products))
        for tp in products:
            try:
                self._check_one(tp)
            except Exception as exc:  # noqa: BLE001 — изолируем сбой товара
                log.warning("Сбой проверки %s/%s: %s", tp.marketplace, tp.sku, exc)

    def _check_one(self, tp) -> None:
        parser = self._parser_for(tp.marketplace)
        product = parser.parse(tp.url or tp.sku)

        if tp.title is None and product.title:
            self.db.update_title(tp.id, product.title)

        prev = tp.last_price
        self.db.record_check(tp.id, product.price, product.in_stock)

        if not product.in_stock:
            log.info("%s — нет в наличии", product.title)
            return

        self._maybe_notify(product, prev, tp.target_price)

    def _maybe_notify(self, product, prev_price, target_price) -> None:
        reasons = []

        # 1) Достигнута целевая цена.
        if target_price is not None and product.price <= target_price:
            reasons.append(f"достигнута целевая цена ≤ {target_price:.0f} ₽")

        # 2) Цена упала относительно прошлой проверки на заданный порог.
        if prev_price is not None and product.price < prev_price:
            drop = (prev_price - product.price) / prev_price
            if drop >= self.drop_threshold:
                reasons.append(
                    f"снижение на {drop * 100:.1f}% "
                    f"({prev_price:.0f} → {product.price:.0f} ₽)"
                )

        if not reasons:
            log.info("%s — без изменений (%.0f ₽)", product.title, product.price)
            return

        text = (
            f"💰 <b>{product.title}</b>\n"
            f"Цена: <b>{product.price:.0f} ₽</b>\n"
            f"{'; '.join(reasons)}\n"
            f'<a href="{product.url}">Открыть товар</a>'
        )
        self.notifier.notify(text)
        log.info("Уведомление отправлено: %s", product.title)

    def close(self) -> None:
        for parser in self._parsers.values():
            try:
                parser.close()
            except Exception:  # noqa: BLE001
                pass
