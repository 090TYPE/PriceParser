"""Десктоп-экран PriceParser на Tkinter.

Одно окно, куда выводится всё: таблица отслеживаемых товаров, поле
добавления, кнопки управления и лог проверок/уведомлений. Сетевые операции
(парсинг, проверка цен) выполняются в фоновом потоке, чтобы не подвешивать UI.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from .core import Config, Tracker
from .notifier.telegram import Notifier, build_notifier
from .parser import detect_marketplace, get_parser
from .storage import Database

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text)


class _QueueNotifier(Notifier):
    """Дублирует уведомления и в реальный канал, и в очередь для лога UI."""

    def __init__(self, inner: Notifier, log_queue: "queue.Queue[str]") -> None:
        self.inner = inner
        self.log_queue = log_queue

    def notify(self, text: str) -> None:
        self.log_queue.put("🔔 " + _strip_html(text).replace("\n", " | "))
        try:
            self.inner.notify(text)
        except Exception as exc:  # noqa: BLE001 — сбой Telegram не должен ронять UI
            self.log_queue.put(f"⚠️ Не удалось отправить в Telegram: {exc}")


class _QueueLogHandler(logging.Handler):
    """Перенаправляет записи логгера tracker'а в очередь UI."""

    def __init__(self, log_queue: "queue.Queue[str]") -> None:
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        self.log_queue.put(self.format(record))


class App(tk.Tk):
    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config_ = config
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self._busy = False
        self._image_urls: dict[int, str] = {}  # id товара -> URL картинки
        self._photo = None  # ссылка на текущее изображение (иначе GC съест)

        self.title("PriceParser — трекер цен WB / Ozon / Яндекс.Маркет")
        self.geometry("1000x620")
        self.minsize(820, 500)

        self._build_add_bar()
        self._build_table()
        self._build_buttons()
        self._build_log()
        self._enable_clipboard()

        # Логи tracker'а -> лог-панель UI.
        handler = _QueueLogHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger("priceparser").addHandler(handler)
        logging.getLogger("priceparser").setLevel(logging.INFO)

        self.after(150, self._drain_log)
        self.refresh()

    # ---- построение виджетов --------------------------------------------
    def _build_add_bar(self) -> None:
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill="x")

        ttk.Label(bar, text="Ссылка / артикул:").pack(side="left")
        self.url_var = tk.StringVar()
        url_entry = ttk.Entry(bar, textvariable=self.url_var)
        url_entry.pack(side="left", fill="x", expand=True, padx=6)
        url_entry.bind("<Return>", lambda _e: self.on_add())
        self._attach_context_menu(url_entry)

        ttk.Label(bar, text="Цель ₽:").pack(side="left")
        self.target_var = tk.StringVar()
        target_entry = ttk.Entry(bar, textvariable=self.target_var, width=8)
        target_entry.pack(side="left", padx=6)
        self._attach_context_menu(target_entry)

        ttk.Label(bar, text="Маркет:").pack(side="left")
        self.market_var = tk.StringVar(value="авто")
        ttk.Combobox(
            bar, textvariable=self.market_var, width=8, state="readonly",
            values=["авто", "wb", "ozon", "yandex"],
        ).pack(side="left", padx=6)

        ttk.Button(bar, text="Добавить", command=self.on_add).pack(side="left")

    def _build_table(self) -> None:
        frame = ttk.Frame(self, padding=(10, 0))
        frame.pack(fill="both", expand=True)

        # Слева — таблица.
        table_frame = ttk.Frame(frame)
        table_frame.pack(side="left", fill="both", expand=True)

        cols = ("id", "market", "title", "price", "target")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=12)
        for col, text, width, anchor in (
            ("id", "#", 40, "center"),
            ("market", "Маркет", 70, "center"),
            ("title", "Товар", 320, "w"),
            ("price", "Цена ₽", 90, "e"),
            ("target", "Цель ₽", 80, "e"),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Подсветка достигнутой цели.
        self.tree.tag_configure("goal", background="#d8f5d8")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.on_open_browser)

        # Справа — превью картинки выбранного товара.
        preview = ttk.LabelFrame(frame, text="Превью", padding=8)
        preview.pack(side="right", fill="y", padx=(8, 0))
        self.image_label = ttk.Label(
            preview, text="(выберите товар)", anchor="center",
            width=26, justify="center",
        )
        self.image_label.pack(fill="both", expand=True)

    def _build_buttons(self) -> None:
        bar = ttk.Frame(self, padding=(10, 6))
        bar.pack(fill="x")
        self.check_btn = ttk.Button(bar, text="Проверить цены", command=self.on_check)
        self.check_btn.pack(side="left")
        ttk.Button(bar, text="Удалить выбранное", command=self.on_remove).pack(side="left", padx=6)
        ttk.Button(bar, text="Обновить", command=self.refresh).pack(side="left")

        self.status_var = tk.StringVar(value="Готов")
        ttk.Label(bar, textvariable=self.status_var).pack(side="right")

    def _build_log(self) -> None:
        frame = ttk.LabelFrame(self, text="Журнал", padding=(6, 4))
        frame.pack(fill="both", expand=False, padx=10, pady=(0, 10))
        self.log = tk.Text(frame, height=8, wrap="word", state="disabled",
                           font=("Consolas", 9))
        lsb = ttk.Scrollbar(frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set)
        self.log.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")

    # ---- лог -------------------------------------------------------------
    def log_line(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"{ts}  {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain_log(self) -> None:
        try:
            while True:
                self.log_line(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(150, self._drain_log)

    # ---- данные ----------------------------------------------------------
    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._image_urls.clear()
        with Database(self.config_.db_path) as db:
            products = db.list_products()
        for tp in products:
            price = f"{tp.last_price:.0f}" if tp.last_price else "—"
            target = f"{tp.target_price:.0f}" if tp.target_price else "—"
            reached = (
                tp.target_price is not None
                and tp.last_price is not None
                and tp.last_price <= tp.target_price
            )
            self.tree.insert(
                "", "end", iid=str(tp.id),
                values=(tp.id, tp.marketplace, tp.title or tp.sku, price, target),
                tags=("goal",) if reached else (),
            )
            self._image_urls[tp.id] = tp.image_url or ""
        self.status_var.set(f"Товаров: {len(products)}")

    # ---- действия --------------------------------------------------------
    def _set_busy(self, busy: bool, status: str = "") -> None:
        self._busy = busy
        self.check_btn.configure(state="disabled" if busy else "normal")
        if status:
            self.status_var.set(status)

    def on_add(self) -> None:
        if self._busy:
            return
        url = self.url_var.get().strip()
        if not url:
            return
        target = None
        raw_target = self.target_var.get().strip().replace(" ", "")
        if raw_target:
            try:
                target = float(raw_target)
            except ValueError:
                messagebox.showerror("Ошибка", "Цель должна быть числом")
                return
        market = self.market_var.get()
        market = None if market == "авто" else market

        self._set_busy(True, "Добавляю...")
        threading.Thread(
            target=self._add_worker, args=(url, target, market), daemon=True
        ).start()

    def _add_worker(self, url: str, target, market) -> None:
        try:
            if market is None and url.isdigit():
                self.log_queue.put(
                    "⚠️ Для голого артикула выберите маркетплейс "
                    "(wb / ozon / yandex) — по числу его не определить."
                )
                return
            marketplace = market or detect_marketplace(url)
            parser = get_parser(marketplace)
            try:
                product = parser.parse(url)
            finally:
                parser.close()
            with Database(self.config_.db_path) as db:
                pid = db.add_product(
                    marketplace=marketplace, sku=product.sku, url=product.url,
                    title=product.title, target_price=target,
                    image_url=product.image_url,
                )
                db.record_check(pid, product.price, product.in_stock)
            self.log_queue.put(f"➕ Добавлен [{marketplace}] {product}")
        except Exception as exc:  # noqa: BLE001
            self.log_queue.put(f"⚠️ Не удалось добавить: {exc}")
        finally:
            self.after(0, self._after_action)

    def on_check(self) -> None:
        if self._busy:
            return
        self._set_busy(True, "Проверяю цены...")
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self) -> None:
        try:
            with Database(self.config_.db_path) as db:
                notifier = _QueueNotifier(build_notifier(self.config_), self.log_queue)
                tracker = Tracker(db, notifier, self.config_.price_drop_threshold)
                try:
                    tracker.check_all()
                finally:
                    tracker.close()
        except Exception as exc:  # noqa: BLE001
            self.log_queue.put(f"⚠️ Ошибка проверки: {exc}")
        finally:
            self.after(0, self._after_action)

    def _after_action(self) -> None:
        self._set_busy(False)
        self.url_var.set("")
        self.target_var.set("")
        self.refresh()

    def on_remove(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        pid = int(sel[0])
        with Database(self.config_.db_path) as db:
            db.remove_product(pid)
        self.log_queue.put(f"🗑️ Удалён товар #{pid}")
        self._show_image(None, "(выберите товар)")
        self.refresh()

    # ---- буфер обмена (кросс-раскладочная вставка) -----------------------
    def _enable_clipboard(self) -> None:
        """На русской раскладке Tk не ловит Ctrl+V (keysym кириллический),
        поэтому привязываем действия к кириллическим клавишам тех же кнопок."""
        # V→м(em), C→с(es), X→ч(che), A→ф(ef) в раскладке ЙЦУКЕН.
        binds = {
            "<Control-Cyrillic_em>": "<<Paste>>",
            "<Control-Cyrillic_es>": "<<Copy>>",
            "<Control-Cyrillic_che>": "<<Cut>>",
            "<Control-Cyrillic_ef>": "<<SelectAll>>",
        }
        for cls in ("TEntry", "Text", "TCombobox", "Entry"):
            for seq, virt in binds.items():
                self.bind_class(
                    cls, seq,
                    lambda e, v=virt: (e.widget.event_generate(v), "break")[1],
                )

    def _attach_context_menu(self, widget) -> None:
        """Правый клик по полю -> Вырезать/Копировать/Вставить."""
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(
            label="Вырезать", command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(
            label="Копировать", command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(
            label="Вставить", command=lambda: widget.event_generate("<<Paste>>"))

        def popup(event):
            widget.focus_set()
            menu.tk_popup(event.x_root, event.y_root)

        widget.bind("<Button-3>", popup)

    # ---- картинка товара -------------------------------------------------
    def on_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        pid = int(sel[0])
        url = self._image_urls.get(pid, "")
        if not url:
            self._show_image(None, "(нет изображения)")
            return
        self._show_image(None, "Загрузка…")
        threading.Thread(
            target=self._image_worker, args=(pid, url), daemon=True
        ).start()

    def _image_worker(self, pid: int, url: str) -> None:
        try:
            import io

            import requests
            from PIL import Image

            r = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0",
                         "Referer": "https://www.wildberries.ru/"},
                timeout=15,
            )
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content))
            img.load()
            img.thumbnail((240, 240))
            # PhotoImage создаём в главном потоке (Tk не потокобезопасен).
            self.after(0, lambda: self._render_image(pid, img))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda: self._show_image(None, f"(ошибка: {exc})"))

    def _render_image(self, pid: int, pil_img) -> None:
        sel = self.tree.selection()
        if not sel or int(sel[0]) != pid:
            return  # пользователь уже выбрал другой товар
        from PIL import ImageTk

        self._photo = ImageTk.PhotoImage(pil_img)  # держим ссылку от GC
        self.image_label.configure(image=self._photo, text="")

    def _show_image(self, photo, text: str) -> None:
        self._photo = photo
        self.image_label.configure(image=photo or "", text=text)

    def on_open_browser(self, _event=None) -> None:
        """Двойной клик по строке — открыть товар в браузере."""
        sel = self.tree.selection()
        if not sel:
            return
        pid = int(sel[0])
        with Database(self.config_.db_path) as db:
            for tp in db.list_products():
                if tp.id == pid and tp.url:
                    import webbrowser

                    webbrowser.open(tp.url)
                    break


def run(config: Config | None = None) -> None:
    App(config or Config.from_env()).mainloop()


if __name__ == "__main__":
    run()
