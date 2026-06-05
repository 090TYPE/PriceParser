"""Командный интерфейс PriceParser."""

from __future__ import annotations

import argparse
import logging
import sys

from apscheduler.schedulers.blocking import BlockingScheduler

from .core import Config, Tracker
from .notifier.telegram import build_notifier
from .parser import detect_marketplace, get_parser
from .storage import Database


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_add(args, config: Config) -> int:
    marketplace = args.marketplace or detect_marketplace(args.url)
    parser = get_parser(marketplace)
    try:
        product = parser.parse(args.url)
    finally:
        parser.close()

    with Database(config.db_path) as db:
        pid = db.add_product(
            marketplace=marketplace,
            sku=product.sku,
            url=product.url,
            title=product.title,
            target_price=args.target,
            image_url=product.image_url,
        )
        db.record_check(pid, product.price, product.in_stock)

    tgt = f", цель ≤ {args.target:.0f} ₽" if args.target else ""
    print(f"[#{pid}] добавлен: {product} ({marketplace}{tgt})")
    return 0


def cmd_list(args, config: Config) -> int:
    with Database(config.db_path) as db:
        products = db.list_products()
    if not products:
        print("Список пуст. Добавьте товар: priceparser add <url>")
        return 0
    for tp in products:
        last = f"{tp.last_price:.0f} ₽" if tp.last_price else "—"
        tgt = f" (цель ≤ {tp.target_price:.0f})" if tp.target_price else ""
        print(f"#{tp.id} [{tp.marketplace}] {tp.title or tp.sku} — {last}{tgt}")
    return 0


def cmd_remove(args, config: Config) -> int:
    with Database(config.db_path) as db:
        ok = db.remove_product(args.id)
    print("Удалено" if ok else f"Товар #{args.id} не найден")
    return 0 if ok else 1


def cmd_check(args, config: Config) -> int:
    """Однократная проверка всех товаров."""
    with Database(config.db_path) as db:
        tracker = Tracker(db, build_notifier(config), config.price_drop_threshold)
        try:
            tracker.check_all()
        finally:
            tracker.close()
    return 0


def cmd_ui(args, config: Config) -> int:
    """Запустить графический экран."""
    from .ui import run

    run(config)
    return 0


def cmd_run(args, config: Config) -> int:
    """Периодическая проверка по расписанию."""
    interval = args.interval or config.check_interval
    with Database(config.db_path) as db:
        tracker = Tracker(db, build_notifier(config), config.price_drop_threshold)
        scheduler = BlockingScheduler()
        scheduler.add_job(tracker.check_all, "interval", seconds=interval)
        print(f"Запущен трекер, интервал {interval} c. Ctrl+C для остановки.")
        tracker.check_all()  # первая проверка сразу
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            print("\nОстановка...")
        finally:
            tracker.close()
    return 0


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="priceparser", description="Трекер цен WB/Ozon")
    sub = p.add_subparsers(dest="command", required=True)

    pa = sub.add_parser("add", help="добавить товар по ссылке")
    pa.add_argument("url", help="ссылка на товар (или артикул при --marketplace)")
    pa.add_argument("--marketplace", choices=["wb", "ozon", "yandex"], help="если не определяется по URL")
    pa.add_argument("--target", type=float, help="целевая цена для уведомления")
    pa.set_defaults(func=cmd_add)

    pl = sub.add_parser("list", help="показать отслеживаемые товары")
    pl.set_defaults(func=cmd_list)

    pr = sub.add_parser("remove", help="удалить товар по id")
    pr.add_argument("id", type=int)
    pr.set_defaults(func=cmd_remove)

    pc = sub.add_parser("check", help="проверить цены один раз")
    pc.set_defaults(func=cmd_check)

    pui = sub.add_parser("ui", help="открыть графический экран")
    pui.set_defaults(func=cmd_ui)

    prun = sub.add_parser("run", help="запустить периодическую проверку")
    prun.add_argument("--interval", type=int, help="интервал в секундах")
    prun.set_defaults(func=cmd_run)

    return p


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    args = build_argparser().parse_args(argv)
    config = Config.from_env()
    return args.func(args, config)


if __name__ == "__main__":
    sys.exit(main())
