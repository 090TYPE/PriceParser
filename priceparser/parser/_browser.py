"""Создание Selenium-драйвера для парсеров Ozon/Яндекса.

История: undetected-chromedriver (3.5.5, последняя версия) ломается на Chrome
148 — патченный браузер закрывает вкладку сразу после старта
(NoSuchWindowException "target window already closed"). Поэтому по умолчанию
используем обычный Selenium: встроенный Selenium Manager (selenium>=4.6) сам
скачивает драйвер под установленный Chrome, и бага с закрытием окна нет.

uc можно принудительно включить переменной окружения PRICEPARSER_USE_UC=1
(если в будущем выйдет совместимая версия).
"""

from __future__ import annotations

import os
import re

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)


# Маркеры страниц блокировки (антибот / капча / VPN) у Ozon и Яндекса.
_BLOCK_MARKERS = (
    "похоже, нет соединения",
    "используете vpn",
    "используете прокси",
    "подтвердите, что запросы",
    "доступ ограничен",
    "are you a robot",
    "captcha",
    "ddos-guard",
)


class BlockedError(RuntimeError):
    """Сайт показал страницу антибота/капчи/VPN вместо карточки товара."""


def raise_if_blocked(title: str, site: str) -> None:
    """Если заголовок страницы похож на блокировку — кинуть понятную ошибку."""
    # Нормализуем неразрывные пробелы (\xa0) и схлопываем пробелы.
    low = re.sub(r"\s+", " ", (title or "").replace("\xa0", " ")).lower()
    if any(marker in low for marker in _BLOCK_MARKERS):
        raise BlockedError(
            f"{site} показал страницу блокировки ('{title.strip()}'). "
            f"Вероятные причины: включён VPN/прокси (выключите Karing) "
            f"или сработал антибот. WB-парсер работает без браузера."
        )


def detect_chrome_major() -> int | None:
    """Вернуть мажорную версию установленного Chrome или None."""
    try:
        import winreg

        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r"Software\Google\Chrome\BLBeacon") as k:
                    version, _ = winreg.QueryValueEx(k, "version")
                    return int(version.split(".")[0])
            except OSError:
                continue
    except ImportError:
        pass

    import shutil
    import subprocess

    for name in ("chrome", "google-chrome", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if not path:
            continue
        try:
            out = subprocess.run(
                [path, "--version"], capture_output=True, text=True, timeout=10
            ).stdout
            m = re.search(r"(\d+)\.\d+", out)
            if m:
                return int(m.group(1))
        except Exception:  # noqa: BLE001
            continue
    return None


def _make_uc_driver(headless: bool):
    import undetected_chromedriver as uc

    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,1024")
    return uc.Chrome(options=options, version_main=detect_chrome_major())


def _make_plain_driver(headless: bool):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,1024")
    options.add_argument(f"--user-agent={_UA}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=ru-RU")
    # Убрать явные следы автоматизации.
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)  # Selenium Manager сам найдёт драйвер
    # navigator.webdriver -> undefined (лёгкая маскировка).
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
        )
    except Exception:  # noqa: BLE001
        pass
    return driver


def make_driver(headless: bool = True):
    """Создать драйвер. По умолчанию обычный Selenium; uc — по флагу."""
    if os.getenv("PRICEPARSER_USE_UC") == "1":
        return _make_uc_driver(headless)
    return _make_plain_driver(headless)
