#!/usr/bin/env python3
"""
Парсер ссылок на товары с сайта Libex.ru (категория fiction).
Извлекает информацию о книгах из HTML-файла или напрямую с сайта с поддержкой пагинации.
"""
import re
import json
import sys
import time
from urllib.request import urlopen, Request, build_opener, install_opener, HTTPCookieProcessor
from urllib.error import HTTPError, URLError
from http.cookiejar import CookieJar

# Глобальный CookieJar для поддержания сессии
_cookie_jar = CookieJar()
_opener = build_opener(HTTPCookieProcessor(_cookie_jar))
install_opener(_opener)
_session_initialized = False

# Константы
DEFAULT_BASE_URL = 'https://www.libex.ru/cat/fiction/'
DEFAULT_ITEMS_PER_PAGE = 12  # значение по умолчанию на сайте
REQUEST_DELAY = 1.0  # задержка между запросами (сек)
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
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
        
        # Ссылка на изображение
        #img_match = re.search(r'<img[^>]+src="([^"]+)"', book_block)
        #if img_match:
        #    book['image_url'] = img_match.group(1)
        
        # Автор
        author_match = re.search(
            r'<tr><td>(.*?)</td></tr>\s*<tr><td><big>',
            book_block,
            re.DOTALL
        )
        if author_match:
            book['author'] = author_match.group(1).strip()
        
        # Название
        title_match = re.search(
            r'<big><a[^>]*>(.*?)</a></big>',
            book_block,
            re.DOTALL
        )
        if title_match:
            book['title'] = title_match.group(1).strip()
        
        # Год и издательство
        year_pub = re.search(
            r'<tr><td>(.*?)(\d{4})\s*г\.;.*?Изд-во:\s*(.*?)<small',
            book_block,
            re.DOTALL
        )
        if year_pub:
            book['year'] = int(year_pub.group(2))
            book['publisher'] = year_pub.group(3).strip()
        
        # Серия
        series_match = re.search(
            r'Серия:\s*<span class="bigger"><span style="color:#330099">(.*?)</span></span>',
            book_block,
            re.DOTALL
        )
        if series_match:
            book['series'] = series_match.group(1).strip()
        
        # Цена
        #price_match = re.search(
        #    r'<div style="width:7em;float:right;white-space:nowrap;">.*?&nbsp;(\d+)\s*&nbsp;руб',
        #    book_block,
        #    re.DOTALL
        #)
        #if price_match:
        #    book['price'] = int(price_match.group(1))
        
        # Состояние книги
        #cond_match = re.search(
        #    r'<img src="/img/cond/(\d)\.gif"[^>]*alt="Состояние:\s*([^"]*)"',
        #   book_block
        #)
        #if cond_match:
        #    book['condition_code'] = int(cond_match.group(1))
        #    book['condition'] = cond_match.group(2)
        
        if book.get('detail_url'):
            books.append(book)
    
    return books
# Стандартные заголовки браузера для обхода антибот-защиты
_BROWSER_HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': (
        'text/html,application/xhtml+xml,application/xml;q=0.9,'
        'image/avif,image/webp,image/apng,*/*;q=0.8'
    ),
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
    'Referer': 'https://www.libex.ru/',
    'Connection': 'keep-alive',
}


def fetch_page(url):
    """
    Загружает HTML-содержимое страницы с сайта Libex.ru.
    Выполняет предварительный запрос к корню сайта для получения
    cookie-сессии, необходимой для преодоления антибот-защиты.

    Args:
        url (str): Полный URL страницы.

    Returns:
        str: HTML содержимое страницы в кодировке cp1251.

    Raises:
        HTTPError: При ошибке HTTP.
        URLError: При сетевой ошибке.
    """
    global _session_initialized

    # Перед первым запросом к целевой странице посещаем корень,
    # чтобы получить необходимые cookie (libex_uid и libex_welcome_here2)
    if not _session_initialized:
        _session_initialized = True
        root_req = Request('https://www.libex.ru/',
                           headers=_BROWSER_HEADERS)
        with urlopen(root_req) as resp:
            resp.read()  # читаем, но не используем

    req = Request(url, headers=_BROWSER_HEADERS)
    with urlopen(req) as response:
        raw_data = response.read()
        content = raw_data.decode('cp1251')

    # Проверка на антибот-защиту ("Try harder")
    if 'Try harder' in content:
        raise HTTPError(
            url=url,
            code=403,
            msg='Anti-bot protection triggered. Need valid session.',
            hdrs=getattr(response, 'headers', {}),
            fp=None
        )

    return content
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
def crawl_libex(base_url, start_page=0, end_page=None, max_pages=None,
                delay=REQUEST_DELAY, verbose=True):
    """
    Обходит страницы каталога Libex.ru с поддержкой пагинации.

    Args:
        base_url (str): Базовый URL категории.
        start_page (int): Начальная страница (0-based).
        end_page (int): Конечная страница (не включая), если None — до последней.
        max_pages (int): Максимальное количество страниц для обхода.
        delay (float): Задержка между запросами в секундах.
        verbose (bool): Выводить прогресс в stderr.

    Returns:
        list: Полный список книг со всех страниц.
    """
    all_books = []
    total_pages_known = None
    fetched_pages = 0

    page = start_page
    while True:
        # Проверяем лимиты
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
            print(f'[Ошибка HTTP {e.code}] на странице {page + 1}: {url}',
                  file=sys.stderr)
            break
        except URLError as e:
            print(f'[Сетевая ошибка] на странице {page + 1}: {e.reason}',
                  file=sys.stderr)
            break

        books = extract_books_from_html(content)
        pagination = extract_pagination_info(content)

        if not books:
            if verbose:
                print(f'[Страница {page + 1}] Книги не найдены. Завершаем.',
                      file=sys.stderr)
            break

        all_books.extend(books)
        fetched_pages += 1

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

        # Задержка между запросами
        if delay > 0:
            time.sleep(delay)

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


def save_detail_urls(books, output_path):
    """
    Сохраняет все detail_url из списка книг в текстовый файл,
    по одному URL на строку.
    
    Args:
        books (list): Список книг.
        output_path (str): Путь к выходному текстовому файлу.
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        for book in books:
            url = book.get('detail_url')
            if url:
                f.write(url + '\n')


def main():
    """Главная функция для запуска парсера."""
    import argparse
    
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
        '--quiet',
        action='store_true',
        help='Не выводить прогресс в stderr'
    )
    parser.add_argument(
        '--info',
        action='store_true',
        help='Показать информацию о пагинации из локального HTML файла и выйти'
    )
    
    args = parser.parse_args()
    verbose = not args.quiet
    
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
            
            save_to_json(books, args.output)
            print(f"Найдено книг: {len(books)}")
            print(f"Результат сохранён в: {args.output}")
            
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
            
            books = crawl_libex(
                base_url=args.url,
                start_page=args.start_page,
                end_page=args.end_page,
                max_pages=args.max_pages,
                delay=args.delay,
                verbose=verbose,
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
            
            # Сохраняем
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            
            print(f"Найдено книг: {len(books)}")
            print(f"Результат сохранён в: {args.output}")
        
        # Сохраняем detail_url в detail.txt (для всех режимов, где есть книги)
        if books:
            save_detail_urls(books, 'detail.txt')
            print(f"Ссылки сохранены в: detail.txt")
        
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
    