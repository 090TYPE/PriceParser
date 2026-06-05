"""Хранилище SQLite: отслеживаемые товары и история цен."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    marketplace  TEXT NOT NULL,
    sku          TEXT NOT NULL,
    url          TEXT NOT NULL,
    title        TEXT,
    target_price REAL,          -- уведомить при цене <= target_price (может быть NULL)
    last_price   REAL,          -- цена на прошлой проверке
    image_url    TEXT,          -- ссылка на картинку товара
    created_at   TEXT NOT NULL,
    UNIQUE(marketplace, sku)
);

CREATE TABLE IF NOT EXISTS price_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    price      REAL NOT NULL,
    in_stock   INTEGER NOT NULL DEFAULT 1,
    checked_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_product ON price_history(product_id);
"""


@dataclass
class TrackedProduct:
    id: int
    marketplace: str
    sku: str
    url: str
    title: Optional[str]
    target_price: Optional[float]
    last_price: Optional[float]
    image_url: Optional[str] = None


class Database:
    def __init__(self, path: str = "priceparser.db") -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_SCHEMA)
        # Миграция для баз, созданных до появления колонки image_url.
        try:
            self.conn.execute("ALTER TABLE products ADD COLUMN image_url TEXT")
        except sqlite3.OperationalError:
            pass  # колонка уже есть
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- товары ----------------------------------------------------------
    def add_product(
        self,
        marketplace: str,
        sku: str,
        url: str,
        title: str | None = None,
        target_price: float | None = None,
        image_url: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO products(marketplace, sku, url, title, target_price, image_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(marketplace, sku) DO UPDATE SET
                   url=excluded.url,
                   target_price=excluded.target_price,
                   image_url=COALESCE(excluded.image_url, products.image_url)""",
            (marketplace, sku, url, title, target_price, image_url,
             datetime.utcnow().isoformat()),
        )
        self.conn.commit()
        return cur.lastrowid

    def remove_product(self, product_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def list_products(self) -> list[TrackedProduct]:
        rows = self.conn.execute(
            "SELECT id, marketplace, sku, url, title, target_price, last_price, image_url "
            "FROM products ORDER BY id"
        ).fetchall()
        return [
            TrackedProduct(
                id=r["id"],
                marketplace=r["marketplace"],
                sku=r["sku"],
                url=r["url"],
                title=r["title"],
                target_price=r["target_price"],
                last_price=r["last_price"],
                image_url=r["image_url"],
            )
            for r in rows
        ]

    def record_check(self, product_id: int, price: float, in_stock: bool) -> None:
        """Записать результат проверки в историю и обновить last_price."""
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            "INSERT INTO price_history(product_id, price, in_stock, checked_at) "
            "VALUES (?, ?, ?, ?)",
            (product_id, price, int(in_stock), now),
        )
        self.conn.execute(
            "UPDATE products SET last_price = ?, title = COALESCE(title, title) "
            "WHERE id = ?",
            (price, product_id),
        )
        self.conn.commit()

    def update_title(self, product_id: int, title: str) -> None:
        self.conn.execute(
            "UPDATE products SET title = ? WHERE id = ?", (title, product_id)
        )
        self.conn.commit()

    def get_price_history(self, product_id: int) -> list[tuple[str, float]]:
        rows = self.conn.execute(
            "SELECT checked_at, price FROM price_history "
            "WHERE product_id = ? ORDER BY checked_at",
            (product_id,),
        ).fetchall()
        return [(r["checked_at"], r["price"]) for r in rows]
