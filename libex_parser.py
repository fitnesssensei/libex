#!/usr/bin/env python3
"""
Парсер ссылок на товары с сайта Libex.ru (категория fiction).
Извлекает информацию о книгах из HTML-файла или напрямую с сайта с поддержкой пагинации.
"""
import re
import json
import sys
import time
import random
# -- dobavil
try:
    import socks
    SOCKS_AVAILABLE = True
except ImportError:
    SOCKS_AVAILABLE = False
    # --
import threading
from urllib.request import (
    urlopen, Request, build_opener, install_opener, HTTPCookieProcessor, ProxyHandler,
)
from urllib.error import HTTPError, URLError
from http.cookiejar import CookieJar
import socket

#  Глобальный CookieJar для поддержания сессии
_cookie_jar = CookieJar()
_opener = build_opener(HTTPCookieProcessor(_cookie_jar))
install_opener(_opener)

_proxy_url = None  # -- dobavil . URL прокси-сервера (задаётся через --proxy)

_session_initialized = False
_session_lock = threading.Lock()

# Таймаут HTTP-запроса (сек) — чтобы скрипт не зависал навсегда
REQUEST_TIMEOUT = 20

# Число попыток загрузки одной страницы перед тем, как признать её "неудачной".
# Временные сетевые сбои (Connection reset, таймауты) обычно проходят со 2-3 попытки.
MAX_RETRIES = 5
# Стартовая задержка между повторами (сек). Растёт экспоненциально: 3 -> 6 -> 12 -> 24 -> 48.
RETRY_BACKOFF_BASE = 3.0
# Случайный разброс задержки (джиттер), чтобы повторы не шли строго синхронно.
RETRY_BACKOFF_JITTER = 2.0

# HTTP-коды, которые считаем временными и стоит повторить запрос.
# (сервер перегружен / намеренно замедляет нас / даёт привратник антибота)
RETRYABLE_HTTP_CODES = {403, 429, 500, 502, 503, 504}

# Константы
# ссылка на категории для паорсинга 

DEFAULT_BASE_URL = 'https://www.libex.ru/'
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/cyber/'  # computers 544.      696
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/educ/'  # наука 7852
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/school/'  # shkola 1693
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/personal/'  # семья дом и дача 1452
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/moto/'  # tehnica 1893
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/health/'  # med.sport.zdorov 1930      696 stroka
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/politics/'  # politik 4106
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/ref/'  # special 1337
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/culture/'  # kultura 3461
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/hobby/'  # hobbi 527
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/mistiq/'  # mistik 913
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/other.html'  # raznoe 70.     629 stroka
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/business/'  # деловая
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/fiction/' # Худ литра
#DEFAULT_BASE_URL = 'https://www.libex.ru/cat/child/'  # детская

DEFAULT_ITEMS_PER_PAGE = 12  # значение по умолчанию на сайте
REQUEST_DELAY = 10.0  # задержка между запросами (сек)
USER_AGENTS = [
    # 1 — Windows 10, Chrome 120
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    # 2 — Windows 11, Firefox 121
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    # 3 — macOS Sonoma 14, Safari 17.1
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    # 4 — Windows 10, Edge 120
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    # 5 — Linux Ubuntu, Chrome 120
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    # 6 — Windows 10, Opera 106
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0',
    # 7 — macOS Ventura 13, Firefox 121
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 13.6; rv:121.0) Gecko/20100101 Firefox/121.0',
    # 8 — Android 14, Chrome 120 (мобильный)
    'Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
    # 9 — iPhone iOS 17, Safari (мобильный)
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1',
    # 10 — Windows 11, Chrome 119 (чуть старше)
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
]
USER_AGENT = USER_AGENTS[0]  # для обратной совместимости
def extract_pagination_info(content):
    """
    Извлекает информацию о пагинации из HTML-содержимого.
    
    Args:
        content (str): HTML-содержимое страницы.
    
    Returns:`
        dict: Словарь с ключами:
            - current_page (int): текущая страница (0-based)
            - total_pages (int): общее количество страниц
            - last_page_url (str): URL последней страницы
            - pages (list): список доступных номеров страниц в навигации
    """
    info = {
        'current_page': None,
        'total_pages': None,
        'last_page_url': None,
        'pages': [],
    }
    
    # Ищем текущую выбранную страницу
    current_match = re.search(
        r'<td class="selected"><a href="\?pg=(\d+)">(\d+)</a></td>',
        content
    )
    if current_match:
        info['current_page'] = int(current_match.group(1))
    
    # Ищем ссылку на последнюю страницу
    last_match = re.search(
        r'<a href="\?pg=(\d+)"><img[^>]+alt="[Нн]а последнюю страницу"',
        content
    )
    if last_match:
        info['total_pages'] = int(last_match.group(1)) + 1  # 0-based → количество
        info['last_page_url'] = f'?pg={last_match.group(1)}'
    
    # Все видимые страницы в пагинаторе
    page_links = re.findall(
        r'<td[^>]*><a href="\?pg=(\d+)">(\d+)</a></td>',
        content
    )
    for pg_num_str, display_num in page_links:
        info['pages'].append(int(pg_num_str))
    
    # Сортируем и убираем дубликаты
    info['pages'] = sorted(set(info['pages']))
    
    return info
def extract_books_from_html(content):
    """
    Парсит HTML содержимое страницы Libex и извлекает список книг.

    Args:
        content (str): HTML содержимое страницы.

    Returns:
        list: Список словарей с данными о книгах.
    """
    books = []

    # Разбиваем на блоки книг по паттерну открывающего div
    book_blocks = re.findall(
        r'<div style="border-bottom:1px solid #330066;padding:0\.35em 0em 0\.35em 0em;">(.*?)<br clear="all" />\s*</div>',
        content,
        re.DOTALL
    )

    for book_block in book_blocks:
        book = {}

        # Ссылка на детальную страницу
        detail_match = re.search(r'href="(/detail/book\d+\.html)"', book_block)
        if detail_match:
            book['detail_url'] = 'https://www.libex.ru' + detail_match.group(1)

        # ---- Короткая запись (закомментирована - полная информация
        #       собирается в libex_detail_worker.py) ----

        # # Ссылка на изображение
        # #img_match = re.search(r'<img[^>]+src="([^"]+)"', book_block)
        # #if img_match:
        # #    book['image_url'] = img_match.group(1)

        # # Автор
        # author_match = re.search(
        #     r'<tr><td>(.*?)</td></tr>\s*<tr><td><big>',
        #     book_block,
        #     re.DOTALL
        # )
        # if author_match:
        #     book['author'] = author_match.group(1).strip()

        # # Название
        # title_match = re.search(
        #     r'<big><a[^>]*>(.*?)</a></big>',
        #     book_block,
        #     re.DOTALL
        # )
        # if title_match:
        #     book['title'] = title_match.group(1).strip()

        # # Год и издательство
        # year_pub = re.search(
        #     r'<tr><td>(.*?)(\d{4})\s*г\.;.*?Изд-во:\s*(.*?)<small',
        #     book_block,
        #     re.DOTALL
        # )
        # if year_pub:
        #     book['year'] = int(year_pub.group(2))
        #     book['publisher'] = year_pub.group(3).strip()

        # # Серия
        # series_match = re.search(
        #     r'Серия:\s*<span class="bigger"><span style="color:#330099">(.*?)</span></span>',
        #     book_block,
        #     re.DOTALL
        # )
        # if series_match:
        #     book['series'] = series_match.group(1).strip()

        if book.get('detail_url'):
            books.append(book)

    return books
def _get_browser_headers():
    """Возвращает заголовки браузера со случайным User-Agent (из пула 10 шт)."""
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': (
            'text/html,application/xhtml+xml,application/xml;q=0.9,'
            'image/avif,image/webp,image/apng,*/*;q=0.8'
        ),
        'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
        'Referer': 'https://www.libex.ru/',
        # 'Connection: close' — не использовать keep-alive между запросами.
        # urllib пулит (переиспользует) TCP-соединения, но после долгой паузы
        # (delay между страницами) сервер обычно закрывает такой сокет, и следующий
        # запрос уходит по уже закрытому соединению → получаем
        # "[Errno 54] Connection reset by peer". Каждый запрос открывает новое
        # соединение, зато исключает этот класс сбоев.
        'Connection': 'close',
    }

# -- dobavil
def setup_proxy(proxy_url):
    """
    Настраивает прокси для всех HTTP-запросов.
    Поддерживает HTTP/HTTPS прокси и SOCKS5 (через PySocks + SSH-туннель).
    Args:
        proxy_url (str): URL прокси, например:
            - 'http://178.20.41.120:3128'
            - 'socks5://127.0.0.1:1080'  (для SSH-туннеля)
            - None / '' — отключить прокси
    """
    global _proxy_url, _opener, _cookie_jar
    if not proxy_url:
        _proxy_url = None
        # Возвращаем стандартный opener (без прокси)
        _cookie_jar = CookieJar()
        _opener = build_opener(HTTPCookieProcessor(_cookie_jar))
        install_opener(_opener)
        return
    _proxy_url = proxy_url
    # SOCKS5-прокси (socks5:// or socks5h://)
    if proxy_url.startswith('socks5'):
        if not SOCKS_AVAILABLE:
            print("Ошибка: Для SOCKS5-прокси нужен PySocks: pip3 install PySocks",
                  file=sys.stderr)
            sys.exit(1)
        # Парсим socks5://[user:pass@]host:port
        socks_part = proxy_url.split('://')[1]
        # Отделяем опциональные креды user:pass@ от host:port
        userinfo = None
        if '@' in socks_part:
            userinfo, socks_part = socks_part.rsplit('@', 1)
        if ':' in socks_part:
            host, port_str = socks_part.rsplit(':', 1)
            port = int(port_str)
        else:
            host = socks_part
            port = 1080
        # Креды (если были заданы)
        username = None
        password = None
        if userinfo:
            if ':' in userinfo:
                username, password = userinfo.split(':', 1)
            else:
                username = userinfo
        # Monkey-patch socket.socket — все urlopen() пойдут через SOCKS5
        # ProxyHandler НЕ используем — urllib не понимает схему socks5://
        socks.set_default_proxy(socks.SOCKS5, host, port,
                                username=username, password=password,
                                rdns=True)
        socket.socket = socks.socksocket
        # Opener только с CookieJar (без ProxyHandler)
        _cookie_jar = CookieJar()
        _opener = build_opener(HTTPCookieProcessor(_cookie_jar))
        install_opener(_opener)
    # HTTP/HTTPS-прокси
    elif proxy_url.startswith('http'):
        mapped = {
            'http': proxy_url,
            'https': proxy_url,
        }
        _cookie_jar = CookieJar()
        _opener = build_opener(
            HTTPCookieProcessor(_cookie_jar),
            ProxyHandler(mapped),
        )
        install_opener(_opener)
# ------
def _reset_session():
    """Сбрасывает cookie-сессию и opener.

    На долгих прогонах (сотни страниц) сервер может "протухшить" сессию
    (сбросить/инвалидировать cookie). На случай ретрая заново берём свежие
    cookie с корня сайта, чтобы не ходить со старыми.

    Openеr пересобираем через setup_proxy(), чтобы сохранить текущую
    конфигурацию прокси (если она была задана через --proxy).
    """
    global _proxy_url, _session_initialized
    setup_proxy(_proxy_url if _proxy_url else None)
    _session_initialized = False
    socket.setdefaulttimeout(REQUEST_TIMEOUT)


def _init_session_once():
    """Идемпотентно инициализирует cookie-сессию (с double-checked locking).

    Вызывается перед попыткой загрузки страницы. Если сессия уже инициализирована
    и не была сброшена (_reset_session), ничего не делает.
    """
    global _session_initialized
    if not _session_initialized:
        with _session_lock:
            if not _session_initialized:  # double-checked locking
                _session_initialized = True  # пометим до запроса, чтобы не зациклилось
                root_headers = _get_browser_headers()
                root_req = Request('https://www.libex.ru/', headers=root_headers)
                with urlopen(root_req, timeout=REQUEST_TIMEOUT) as resp:
                    resp.read()  # читаем, но не используем


def _fetch_page_once(url):
    """Одна попытка загрузки страницы (без ретраев).

    Возвращает HTML-строку или выбрасывает HTTPError / URLError.
    Перед запросом инициализирует cookie-сессию, если её ещё нет.
    """
    _init_session_once()

    req = Request(url, headers=_get_browser_headers())
    with urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        raw_data = response.read()
        content = raw_data.decode('cp1251')

    # Проверка на антибот-защиту ("Try harder")
    if 'Try harder' in content:
        raise HTTPError(
            url=url,
            code=403,
            msg='Anti-bot protection triggered. Need valid session.',
            hdrs=getattr(response, 'headers', {}),
            fp=None,
        )

    return content


def fetch_page(url):
    """Загружает HTML-содержимое страницы с сайта Libex.ru с ретраями.

    Выполняет предварительный запрос к корню сайта для получения
    cookie-сессии, необходимой для преодоления антибот-защиты.

    Временные сетевые сбои (Connection reset / Connection refused / таймаут)
    и временные HTTP-коды (403/429/5xx) повторяются с экспоненциальной
    задержкой (MAX_RETRIES попыток всего). Перед каждой повторной попыткой
    cookie-сессия пересоздаётся — это лечит "протухшие" сессии на долгих прогонах
    и антибот-срабатывания.

    Args:
        url (str): Полный URL страницы.

    Returns:
        str: HTML содержимое страницы в кодировке cp1251.

    Raises:
        HTTPError: При устойчивой ошибке HTTP (например, 404 — страница не существует).
        URLError: При устойчивой сетевой ошибке (после всех повторных попыток).
    """
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _fetch_page_once(url)
        except HTTPError as e:
            last_exc = e
            # 404 и прочие "настоящие" ошибки не ретраим — это не временный сбой.
            if e.code not in RETRYABLE_HTTP_CODES:
                raise
        except (URLError, ConnectionResetError, socket.timeout, OSError) as e:
            last_exc = e
            # e.reason для ConnectionResetError это сам объект; берём понятное описание
            reason = getattr(e, 'reason', e)
        except Exception as e:  # noqa: BLE001 — маловероятная неожиданность
            last_exc = e
            reason = e
            print(f'    [fetch_page] неожиданная ошибка: {e!r}', file=sys.stderr)
            raise

        # Повторять только если остались попытки
        if attempt >= MAX_RETRIES:
            break

        # Экспоненциальная задержка с джиттером: 3 -> 6 -> 12 -> 24 -> 48 (±2)
        backoff = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
        delay = backoff + random.uniform(0, RETRY_BACKOFF_JITTER)
        print(
            f'    [Сбой] попытка {attempt}/{MAX_RETRIES} не удалась '
            f'({getattr(last_exc, "reason", last_exc)}). '
            f'Обновляю сессию и повторю через {delay:.1f}с...',
            file=sys.stderr,
        )

        # Перед следующим повтором — свежая cookie-сессия.
        _reset_session()
        time.sleep(delay)

    # Все попытки исчерпаны
    if isinstance(last_exc, HTTPError):
        raise last_exc
    raise last_exc
def parse_libex_html(file_path):
    """
    Парсит локальный HTML файл Libex и извлекает список книг + информацию о пагинации.
    
    Args:
        file_path (str): Путь к HTML файлу.
    
    Returns:
        tuple: (list книг, dict информация о пагинации)
    """
    with open(file_path, 'r', encoding='cp1251') as f:
        content = f.read()
    
    books = extract_books_from_html(content)
    pagination = extract_pagination_info(content)
    
    return books, pagination
def parse_page_range(page_range_str, total_pages=None):
    """
    Парсит строку диапазона страниц в список номеров страниц (0-based).
    
    Поддерживаемые форматы:
        - "1-5" — страницы 1-5 (включительно)
        - "1,3,5" — конкретные страницы
        - "1-3,5,7-10" — смешанные диапазоны
        - "all" — все страницы (требует total_pages)
    
    Args:
        page_range_str (str): Строка с диапазоном страниц (1-based для пользователя).
        total_pages (int, optional): Общее количество страниц для "all".
    
    Returns:
        list: Отсортированный список уникальных номеров страниц (0-based).
    
    Raises:
        ValueError: При некорректном формате.
    """
    if not page_range_str or page_range_str.lower() == 'all':
        if total_pages is None:
            raise ValueError("Для 'all' нужно знать total_pages")
        return list(range(total_pages))
    
    pages = set()
    parts = page_range_str.split(',')
    
    for part in parts:
        part = part.strip()
        if '-' in part:
            # Диапазон: "1-5"
            try:
                start_str, end_str = part.split('-', 1)
                start = int(start_str.strip())
                end = int(end_str.strip())
                if start < 1 or end < 1:
                    raise ValueError("Номера страниц должны быть >= 1")
                if start > end:
                    raise ValueError(f"Начало диапазона ({start}) больше конца ({end})")
                # Конвертируем в 0-based
                pages.update(range(start - 1, end))
            except ValueError as e:
                if "invalid literal" in str(e):
                    raise ValueError(f"Некорректный диапазон: '{part}'")
                raise
        else:
            # Одиночная страница: "3"
            try:
                page_num = int(part)
                if page_num < 1:
                    raise ValueError("Номера страниц должны быть >= 1")
                pages.add(page_num - 1)  # 0-based
            except ValueError as e:
                if "invalid literal" in str(e):
                    raise ValueError(f"Некорректный номер страницы: '{part}'")
                raise
    
    return sorted(pages)


def crawl_libex(base_url, start_page=0, end_page=None, max_pages=None,
                page_range=None, delay=REQUEST_DELAY, verbose=True,
                save_every=10, checkpoint_path='libex_books_checkpoint.json',
                output_path=None, detail_urls_path='detail7.txt'):
    """
    Обходит страницы каталога Libex.ru с поддержкой пагинации.

    Args:
        base_url (str): Базовый URL категории.
        start_page (int): Начальная страница (0-based). Игнорируется, если задан page_range.
        end_page (int): Конечная страница (не включая), если None — до последней. Игнорируется, если задан page_range.
        max_pages (int): Максимальное количество страниц для обхода.
        page_range (list): Список конкретных номеров страниц для обхода (0-based).
        delay (float): Задержка между запросами в секундах.
        verbose (bool): Выводить прогресс в stderr.
        save_every (int): Сохранять промежуточный результат каждые N страниц.
                          0 или None — отключить промежуточное сохранение.
        checkpoint_path (str): Путь к файлу промежуточного сохранения.
        output_path (str): Путь к финальному файлу (используется как шаблон имени
                           для чекпоинта, если не указан checkpoint_path).
        detail_urls_path (str): Путь к файлу со списком detail_url (обновляется
                                при каждом чекпоинте и в самом конце).

    Returns:
        list: Полный список книг со всех страниц.
    """
    all_books = []
    total_pages_known = None
    fetched_pages = 0
    failed_pages = []  # страницы, которые не удалось загрузить после всех ретраев (пропущены)
    # Индекс текущей страницы в page_range (растёт при каждом проходе, даже при пропуске).
    # Отдельно от fetched_pages, который считает только успешно загруженные.
    fetch_index = 0

    # Определяем путь для чекпоинта: если не задан явно, формируем из output_path
    if save_every and save_every > 0:
        if checkpoint_path == 'libex_books_checkpoint.json' and output_path:
            # Если пользователь не менял путь явно, но указал output_path —
            # используем его как шаблон: <name>_checkpoint.json
            import os
            base, ext = os.path.splitext(output_path)
            if base:
                checkpoint_path = f'{base}_checkpoint{ext or ".json"}'

    def _save_checkpoint(books_snapshot, pages_done, current_page_num):
        """Вспомогательная функция для сохранения промежуточного результата."""
        if not save_every or save_every <= 0:
            return
        try:
            checkpoint_data = {
                'meta': {
                    'source': base_url,
                    'total_books': len(books_snapshot),
                    'fetched_pages': pages_done,
                    'last_page': current_page_num,
                    'is_checkpoint': True,
                },
                'books': books_snapshot,
            }
            # === Промежуточное сохранение JSON ОТКЛЮЧЕНО (закомментировано) ===
            # with open(checkpoint_path, 'w', encoding='utf-8') as f:
            #     json.dump(checkpoint_data, f, ensure_ascii=False, indent=2)
            # Также обновляем файл со списком URL — перезаписываем целиком,
            # чтобы при сбое не было дубликатов/пропусков
            try:
                save_detail_urls(books_snapshot, detail_urls_path, mode='w')
            except OSError as e:
                print(f'[Чекпоинт] Не удалось обновить {detail_urls_path}: {e}',
                      file=sys.stderr)
            if verbose:
                print(f'[Чекпоинт] (JSON отключён) Сохранено {len(books_snapshot)} URL '
                      f'после {pages_done} стр. → {detail_urls_path}',
                      file=sys.stderr)
        except OSError as e:
            print(f'[Чекпоинт] Не удалось сохранить промежуточный результат: {e}',
                  file=sys.stderr)

    # Если задан page_range, используем его вместо последовательного обхода
    if page_range is not None:
        pages_to_fetch = page_range
    else:
        # Последовательный режим (как было)
        pages_to_fetch = None
        page = start_page
    
    while True:
        # Определяем следующую страницу для загрузки
        if pages_to_fetch is not None:
            # Режим по списку страниц
            if fetch_index >= len(pages_to_fetch):
                break
            page = pages_to_fetch[fetch_index]

            # Проверяем max_pages (по успешно загруженным страницам)
            if max_pages is not None and fetched_pages >= max_pages:
                break
        else:
            # Последовательный режим
            if max_pages is not None and fetched_pages >= max_pages:
                break
            if end_page is not None and page >= end_page:
                break

        # Формируем URL
        if page == 0:
            url = base_url
        else:
            url = f'{base_url}?pg={page}'

        if verbose:
            total_info = f' / ~{total_pages_known}' if total_pages_known else ''
            print(f'[Страница {page + 1}{total_info}] Загрузка: {url}',
                  file=sys.stderr)

        try:
            content = fetch_page(url)
        except HTTPError as e:
            failed_pages.append((page + 1, url, f'HTTP {e.code}'))
            print(f'[Пропуск] страница {page + 1} не загрузилась после '
                  f'{MAX_RETRIES} попыток (HTTP {e.code}), пропускаю и продолжаю.',
                  file=sys.stderr)
            if pages_to_fetch is not None:
                fetch_index += 1
            else:
                page += 1
            if delay > 0:
                time.sleep(delay)
            continue
        except URLError as e:
            failed_pages.append((page + 1, url, str(e.reason)))
            print(f'[Пропуск] страница {page + 1} не загрузилась после '
                  f'{MAX_RETRIES} попыток ({e.reason}), пропускаю и продолжаю.',
                  file=sys.stderr)
            if pages_to_fetch is not None:
                fetch_index += 1
            else:
                page += 1
            if delay > 0:
                time.sleep(delay)
            continue

        books = extract_books_from_html(content)
        pagination = extract_pagination_info(content)

        if not books:
            if verbose:
                print(f'[Страница {page + 1}] Книги не найдены. Завершаем.',
                      file=sys.stderr)
            break

        all_books.extend(books)
        fetched_pages += 1

        # Промежуточное сохранение каждые save_every страниц
        if save_every and save_every > 0 and fetched_pages % save_every == 0:
            _save_checkpoint(all_books, fetched_pages, page + 1)

        if verbose:
            print(f'[Страница {page + 1}] Найдено книг: {len(books)} '
                  f'(всего: {len(all_books)})', file=sys.stderr)

        # Определяем общее количество страниц при первом запросе
        if total_pages_known is None and pagination.get('total_pages'):
            total_pages_known = pagination['total_pages']
            if verbose:
                print(f'[Инфо] Всего страниц в каталоге: {total_pages_known}',
                      file=sys.stderr)

        # Просто переходим на следующую страницу (+1)
        next_page = page + 1

        # Проверяем, не вышли ли за пределы
        if total_pages_known is not None and next_page >= total_pages_known:
            if verbose:
                print(f'[Готово] Достигнута последняя страница.', file=sys.stderr)
            break

        page = next_page
        fetch_index += 1

        # Задержка между запросами
        if delay > 0:
            time.sleep(delay)

    # Финальное обновление файла со списком URL (на случай, если
    # save_every=0 — промежуточных чекпоинтов не было, но ссылки нужны).
    # Используем try/except, чтобы ошибка записи не маскировала успешный сбор данных.
    if all_books:
        try:
            save_detail_urls(all_books, detail_urls_path, mode='w')
        except OSError as e:
            print(f'[Финал] Не удалось сохранить {detail_urls_path}: {e}',
                  file=sys.stderr)

    # Итоговый отчёт о пропущенных страницах
    if failed_pages:
        print(f'[Итог] Пропущено страниц из-за сбоев: {len(failed_pages)}',
              file=sys.stderr)
        for pg, u, reason in failed_pages:
            print(f'    пропущена страница {pg}: {reason} ({u})', file=sys.stderr)

    return all_books
def save_to_json(books, output_path):
    """
    Сохраняет список книг в JSON файл.
    
    Args:
        books (list): Список книг.
        output_path (str): Путь к выходному JSON файлу.
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(books, f, ensure_ascii=False, indent=2)


def save_detail_urls(books, output_path, mode='w'):
    """
    Сохраняет все detail_url из списка книг в текстовый файл,
    по одному URL на строку.

    Args:
        books (list): Список книг.
        output_path (str): Путь к выходному текстовому файлу.
        mode (str): Режим записи — 'w' (перезапись) или 'a' (дописывание).
    """
    if mode not in ('w', 'a'):
        raise ValueError(f"mode должен быть 'w' или 'a', получено: {mode!r}")
    with open(output_path, mode, encoding='utf-8') as f:
        for book in books:
            url = book.get('detail_url')
            if url:
                f.write(url + '\n')


def main():
    """Главная функция для запуска парсера."""
    import argparse
    import os  # для os.path.exists / os.path.splitext
    
    parser = argparse.ArgumentParser(
        description='Парсер ссылок на товары с Libex.ru'
    )
    parser.add_argument(
        'input',
        nargs='?',
        help='Путь к локальному HTML файлу Libex (если не указан, используется онлайн-режим)'
    )
    parser.add_argument(
        '-o', '--output',
        default='libex_books.json',
        help='Путь к выходному JSON файлу (по умолчанию: libex_books.json)'
    )
    parser.add_argument(
        '--print',
        action='store_true',
        dest='print_output',
        help='Вывести результат в консоль'
    )
    
    # Аргументы для онлайн-режима с пагинацией
    parser.add_argument(
        '--online',
        action='store_true',
        help='Включить онлайн-режим (загрузка с сайта)'
    )
    parser.add_argument(
        '--url',
        default=DEFAULT_BASE_URL,
        help=f'Базовый URL категории (по умолчанию: {DEFAULT_BASE_URL})'
    )
    parser.add_argument(
        '--start-page',
        type=int,
        default=0,
        help='Начальная страница (0-based, по умолчанию: 0)'
    )
    parser.add_argument(
        '--end-page',
        type=int,
        default=None,
        help='Конечная страница (не включая, по умолчанию: до последней)'
    )
    parser.add_argument(
        '--max-pages',
        type=int,
        default=None,
        help='Максимальное количество страниц для обхода'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=REQUEST_DELAY,
        help=f'Задержка между запросами в секундах (по умолчанию: {REQUEST_DELAY})'
    )
    parser.add_argument(
        '--page-range',
        type=str,
        default=None,
        help='Диапазон страниц для загрузки. Форматы: "1-5", "1,3,5", "1-3,5,7-10", "all". Нумерация с 1.'
    )
    parser.add_argument(
        '--save-every',
        type=int,
        default=10,
        help='Сохранять промежуточный результат каждые N страниц '
             '(по умолчанию: 10). 0 — отключить.'
    )
    parser.add_argument(
        '--no-checkpoint',
        action='store_true',
        help='Отключить промежуточное сохранение (эквивалент --save-every 0).'
    )
    parser.add_argument(
        '--checkpoint-path',
        type=str,
        default=None,
        help='Путь к файлу промежуточного сохранения '
             '(по умолчанию: <output>_checkpoint.json).'
    )
    parser.add_argument(
        '--detail-urls-path', '-t', '--txt',
        type=str,
        default='polit4587.txt',
        #default='special1337.txt',
        #default='kultura3489.txt',
        #default='hobbbi527',
        #default='mistik913',
        #default='drugoe70',
        #default='delovaya1152',
        #default='detail15.txt',
        #default='child5000',

        help='Путь к текстовому файлу со списком detail_url '
             '(обновляется при каждом чекпоинте и в самом конце, '
             'по умолчанию: special1337.txt).'
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Не выводить прогресс в stderr'
    )
    parser.add_argument(
        '--info',
        action='store_true',
        help='Показать информацию о пагинации из локального HTML файла и выйти'
    )
    # --dobavil
    parser.add_argument('--proxy', type=str, default=None,
                        help='Прокси-сервер (http://host:port или socks5://host:port)')
    # ---
    args = parser.parse_args()
    setup_proxy(args.proxy) # -- dobavil
    verbose = not args.quiet

     # ── Конец прокси ── старый блок !
    try:
        if args.info and args.input:
            # Режим: показать информацию о пагинации из локального файла
            books, pagination = parse_libex_html(args.input)
            print(f"\n=== Информация о пагинации ===")
            print(f"Текущая страница: {pagination.get('current_page', 'не определено')}")
            print(f"Всего страниц: {pagination.get('total_pages', 'не определено')}")
            if pagination.get('last_page_url'):
                print(f"URL последней страницы: {pagination['last_page_url']}")
            if pagination.get('pages'):
                print(f"Доступные страницы в навигации: "
                      f"{pagination['pages'][:10]}{'...' if len(pagination['pages']) > 10 else ''}")
            print(f"\nНайдено книг на текущей странице: {len(books)}")
            print(f"URL последней книги: "
                  f"{books[-1].get('detail_url', 'N/A') if books else 'N/A'}")
            return
        
        if args.input and not args.online:
            # Локальный режим (как было)
            books, pagination = parse_libex_html(args.input)
            
            if not books:
                print("Не найдено ни одной книги.", file=sys.stderr)
                sys.exit(1)
            
            # === Сохранение JSON в локальном режиме ОТКЛЮЧЕНО (закомментировано) ===
            # save_to_json(books, args.output)
            print(f"Найдено книг: {len(books)}")
            print(f"(JSON-сохранение отключено) Результат НЕ сохранён в: {args.output}")
            
            # Показываем информацию о пагинации, если она есть
            if pagination.get('total_pages'):
                print(f"\nИнформация о пагинации (из файла):")
                print(f"  Текущая страница: {pagination.get('current_page', 'N/A')}")
                print(f"  Всего страниц: {pagination['total_pages']}")
                print(f"  Используйте --online для загрузки всех страниц с сайта")
        else:
            # Онлайн-режим с пагинацией
            if not args.input and not args.online:
                print("Укажите HTML файл или используйте --online для онлайн-режима.",
                      file=sys.stderr)
                sys.exit(1)
            
            # Если указан локальный файл, сначала получаем информацию о пагинации
            if args.input:
                _, pagination = parse_libex_html(args.input)
                if pagination.get('total_pages') and verbose:
                    print(f"[Инфо из файла] Всего страниц: {pagination['total_pages']}",
                          file=sys.stderr)
            
            # Парсим page_range если задан
            page_range = None
            if args.page_range:
                total_pages_for_range = pagination.get('total_pages') if args.input else None
                try:
                    page_range = parse_page_range(args.page_range, total_pages_for_range)
                    if verbose:
                        print(f"[Инфо] Загружаем страницы: {[p+1 for p in page_range]}", file=sys.stderr)
                except ValueError as e:
                    print(f"Ошибка в --page-range: {e}", file=sys.stderr)
                    sys.exit(1)
            
            # Вычисляем параметры промежуточного сохранения
            save_every = 0 if args.no_checkpoint else args.save_every
            if save_every < 0:
                print("Ошибка: --save-every должен быть >= 0", file=sys.stderr)
                sys.exit(1)
            checkpoint_path = args.checkpoint_path
            if checkpoint_path is None:
                _base, _ext = os.path.splitext(args.output)
                checkpoint_path = f'{_base}_checkpoint{_ext or ".json"}'

            books = crawl_libex(
                base_url=args.url,
                start_page=args.start_page,
                end_page=args.end_page,
                max_pages=args.max_pages,
                page_range=page_range,
                delay=args.delay,
                verbose=verbose,
                save_every=save_every,
                checkpoint_path=checkpoint_path,
                output_path=args.output,
                detail_urls_path=args.detail_urls_path,
            )
            
            if not books:
                print("Не найдено ни одной книги.", file=sys.stderr)
                sys.exit(1)
            
            # Добавляем мета-информацию о пагинации в сохранённый JSON
            output_data = {
                'meta': {
                    'source': args.url,
                    'total_books': len(books),
                    'start_page': args.start_page,
                    'end_page': args.end_page or 'last',
                    'fetched_pages': None,  # будет вычислено ниже
                },
                'books': books,
            }
            
            # === Финальное сохранение JSON ОТКЛЮЧЕНО (закомментировано) ===
            # with open(args.output, 'w', encoding='utf-8') as f:
            #     json.dump(output_data, f, ensure_ascii=False, indent=2)

            print(f"Найдено книг: {len(books)}")
            print(f"(JSON-сохранение отключено) Результат НЕ сохранён в: {args.output}")
            # detail.txt уже сохранён внутри crawl_libex (через чекпоинты и/или
            # финальный блок), дополнительно дублируем здесь, чтобы при ошибке
            # во время записи в финале пользователь всё равно получил файл.
            if books and not os.path.exists(args.detail_urls_path):
                save_detail_urls(books, args.detail_urls_path)
                print(f"Ссылки сохранены в: {args.detail_urls_path}")

        if args.print_output:
            books_to_print = books if not args.online else books
            print("\n--- Найденные книги ---")
            for i, book in enumerate(books_to_print, 1):
                print(f"\n{i}. {book.get('author', 'Неизвестный автор')} — "
                      f"{book.get('title', 'Без названия')}")
                print(f"   Цена: {book.get('price', 'Не указана')} руб.")
                print(f"   Ссылка: {book.get('detail_url', 'Нет ссылки')}")
                if book.get('year'):
                    print(f"   Год: {book['year']}")
                if book.get('publisher'):
                    print(f"   Издательство: {book['publisher']}")
                if i >= 50:
                    print(f"\n... и ещё {len(books_to_print) - 50} книг")
                    break
    
    except FileNotFoundError:
        print(f"Ошибка: Файл '{args.input}' не найден.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Ошибка при парсинге: {e}", file=sys.stderr)
        sys.exit(1)
if __name__ == '__main__':
    main()
    