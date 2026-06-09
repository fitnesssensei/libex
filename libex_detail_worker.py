#!/usr/bin/env python3
"""
Воркер для скачивания всей доступной информации о книгах
с детальных страниц Libex.ru (detail/bookXXXXX.html).

Читает список URL из текстового файла (по одному URL на строку),
загружает каждую детальную страницу, извлекает ВСЕ поля,
сохраняет результат в JSON с поддержкой чекпоинтов.

Поддерживает многопоточность для ускорения.

Примеры:
    # Обработать все URL из detail.txt (10 потоков, задержка 1.5с)
    python3 libex_detail_worker.py detail.txt

    # Обработать с 10 потоками, сохранять каждые 50 книг
    python3 libex_detail_worker.py detail.txt -o books_detail.json --threads 10 --save-every 50

    # Использовать 20 потоков без задержки (осторожно!)
    python3 libex_detail_worker.py detail.txt --threads 20 --delay 0

    # Читать URL из большого файла
    python3 libex_detail_worker.py ссылки/detail1400str.txt -o detail1400_parsed.json --threads 15

    # Дозаписать только новые URL (пропустить уже загруженные)
    python3 libex_detail_worker.py detail.txt --resume
"""

import re
import json
import sys
import os
import time
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from libex_parser import fetch_page, USER_AGENT, REQUEST_DELAY

_print_lock = threading.Lock()
_file_lock = threading.Lock()


def extract_book_id(url):
    """Извлекает ID книги из URL вида /detail/book1234567.html"""
    m = re.search(r'/book(\d+)\.html', url)
    return m.group(1) if m else None


def parse_detail_page(html, url):
    """
    Парсит HTML детальной страницы книги и извлекает ВСЮ доступную информацию.

    Args:
        html (str): HTML-содержимое страницы (cp1251).
        url (str): URL страницы (для reference).

    Returns:
        dict: Словарь со всеми полями книги, или None при ошибке парсинга.
    """
    book = {}
    book['detail_url'] = url
    book['book_id'] = extract_book_id(url)

    # ── Из <title> ──
    title_match = re.search(r'<title>\[(.*?)\]\s*(.*?)</title>', html, re.DOTALL)
    if title_match:
        book['title_from_title'] = title_match.group(1).strip()
        book['author_from_title'] = title_match.group(2).strip()

    # ── Из <meta name="description"> ──
    meta_desc = re.search(
        r'<meta name="description" content="(.*?)"',
        html, re.DOTALL
    )
    if meta_desc:
        book['meta_description'] = meta_desc.group(1).strip()

    # ── Категория / раздел каталога ──
    cat_match = re.search(
        r'<b>Каталог:</b>\s*(.*?)(?:</p>|<br)',
        html, re.DOTALL
    )
    if cat_match:
        cat_html = cat_match.group(1)
        categories = re.findall(
            r'<a href="([^"]+)">([^<]+)</a>',
            cat_html
        )
        book['category_path'] = ' > '.join(c[1] for c in categories)
        book['category_urls'] = [c[0] for c in categories]
        if categories:
            book['category'] = categories[-1][1]
            book['category_url'] = 'https://www.libex.ru' + categories[-1][0]

    # ── Автор ──
    author_match = re.search(
        r'<h3 class="nomargin"><a\s+href="/\?cat_author=([^"]+)&amp;author_key=(\d+)"[^>]*>(.*?)</a></h3>',
        html
    )
    if author_match:
        book['author'] = author_match.group(3).strip()
        book['author_key'] = author_match.group(2)
        book['author_search_url'] = '/?cat_author=' + author_match.group(1) + '&author_key=' + author_match.group(2)

    # ── Название ──
    title_match2 = re.search(
        r'<h1 class="nomargin">(.*?)</h1>',
        html, re.DOTALL
    )
    if title_match2:
        book['title'] = title_match2.group(1).strip()

    # ── Серия ──
    series_match = re.search(
        r'<h3 class="nomargin">Серия:\s*(.*?)</h3>',
        html, re.DOTALL
    )
    if series_match:
        book['series'] = series_match.group(1).strip()

    # ── Издательство ──
    publisher_match = re.search(
        r'<tr><td>Издательство:\s*(.*?)</td></tr>',
        html, re.DOTALL
    )
    if publisher_match:
        book['publisher'] = publisher_match.group(1).strip()


    # ── Переплет, страницы, год ──
    binding_match = re.search(
        r'<a href="/qna/ref/binding/">Переплет</a>:\s*(.*?);\s*(\d+)\s+страниц;\s*(\d{4})\s*г\.',
        html
    )
    if binding_match:
        book['binding'] = binding_match.group(1).strip()
        book['pages'] = int(binding_match.group(2))
        book['year'] = int(binding_match.group(3))

    # ── ISBN и Формат ──
    isbn_match = re.search(
        r'<a href="/qna/ref/isbn/">ISBN</a>:\s*([^<;]+)',
        html
    )
    if isbn_match:
        book['isbn'] = isbn_match.group(1).strip()

    format_match = re.search(
        r'<a href="/qna/ref/format/">Формат</a>:\s*([^<;]+)',
        html
    )
    if format_match:
        book['format'] = format_match.group(1).strip()

    # ── Язык ──
    lang_match = re.search(
        r'<tr><td>Язык:\s*(.*?)</td></tr>',
        html, re.DOTALL
    )
    if lang_match:
        book['language'] = re.sub(r'<[^>]+>', '', lang_match.group(1)).strip()

    # ── Дата добавления на сайт ──
    date_match = re.search(
        r'<small class="ltgray">На сайте с\s+(.*?)</small>',
        html
    )
    if date_match:
        book['date_added'] = date_match.group(1).strip()

    # ── Изображение ──
    img_large_match = re.search(
        r'<a href="(/img/x/[^"]+)"><img\s+src="([^"]+)"',
        html
    )
    if img_large_match:
        book['image_large_url'] = 'https://www.libex.ru' + img_large_match.group(1)
        book['image_thumb_url'] = 'https://www.libex.ru' + img_large_match.group(2)
        book['has_image'] = True
    else:
        img_def = re.search(
            r'<img\s+src="(/img/defcover\.jpg)"',
            html
        )
        if img_def:
            book['image_thumb_url'] = 'https://www.libex.ru' + img_def.group(1)
            book['has_image'] = False
        else:
            img_any = re.search(
                r'<img\s+src="(/img/[^"]+)"\s+width="60"',
                html
            )
            if img_any:
                book['image_thumb_url'] = 'https://www.libex.ru' + img_any.group(1)
                book['has_image'] = True

    if 'has_image' not in book:
        book['has_image'] = False

    # ── Счётчик просмотров ──
    counter_match = re.search(
        r'<img\s+src="/chart/cnt\.php\?id=(\d+)&amp;c=1"',
        html
    )
    if counter_match:
        book['view_counter_id'] = counter_match.group(1)

    # ── Аннотация ──
    annotation_match = re.search(
        r'<h3>Аннотация</h3>\s*<p>(.*?)</p>',
        html, re.DOTALL
    )
    if annotation_match:
        ann = annotation_match.group(1)
        ann = re.sub(r'<[^>]+>', '', ann)
        ann = ann.replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        ann = ann.replace('&nbsp;', ' ').replace('&mdash;', '—').replace('&raquo;', '»').replace('&laquo;', '«')
        book['annotation'] = ann.strip()

    # ── Наличие в продаже ──
    if 'сейчас этого издания книги в продаже нет' in html:
        book['in_stock'] = False
        book['in_stock_text'] = 'нет в продаже'
    else:
        # Проверяем, есть ли блок с предложениями
        # Если нет сообщения "нет в продаже", возможно есть таблица с ценами
        stock_section = re.search(
            r'<table[^>]*>\s*<tr><td[^>]*>\s*(.*?)\s*</td></tr>\s*</table>\s*<table[^>]*>\s*<tr><td[^>]*>',
            html, re.DOTALL
        )
        if stock_section:
            content_check = stock_section.group(1)
            if 'нет' in content_check.lower()[:100]:
                book['in_stock'] = False
                book['in_stock_text'] = 'нет в продаже'
            else:
                book['in_stock'] = True
                book['in_stock_text'] = 'в продаже'
        else:
            book['in_stock'] = False
            book['in_stock_text'] = 'нет в продаже'

    # ── Предыдущая / следующая книга в разделе ──
    prev_match = re.search(
        r'<a href="\.(/book\d+\.html)"\s+title="предыдущая книга',
        html
    )
    if prev_match:
        book['prev_book_url'] = 'https://www.libex.ru/detail' + prev_match.group(1)

    next_match = re.search(
        r'<a href="\.(/book\d+\.html)"\s+title="следующая книга',
        html
    )
    if next_match:
        book['next_book_url'] = 'https://www.libex.ru/detail' + next_match.group(1)

    # ── Проверяем, что извлекли хотя бы что-то значимое ──
    if not any(k in book for k in ('title', 'author', 'isbn', 'publisher')):
        return None

    return book


def fetch_and_parse(url, delay=REQUEST_DELAY, retries=3):
    """
    Загружает и парсит одну детальную страницу книги.

    Args:
        url (str): Полный URL страницы.
        delay (float): Задержка перед запросом (для rate limiting).
        retries (int): Количество повторных попыток при ошибке.

    Returns:
        tuple: (url, book_dict_or_None, error_message_or_None)
    """
    if delay > 0:
        time.sleep(delay)

    last_error = None
    for attempt in range(retries):
        try:
            html = fetch_page(url)
            book = parse_detail_page(html, url)
            if book is None:
                return (url, None, 'Не удалось распознать структуру страницы')
            return (url, book, None)
        except HTTPError as e:
            last_error = f'HTTP {e.code}'
            if e.code == 403:
                time.sleep(delay * 3)
            elif e.code == 404:
                return (url, None, f'HTTP {e.code}')
            else:
                time.sleep(delay)
        except URLError as e:
            last_error = f'URL Error: {e.reason}'
            time.sleep(delay)
        except Exception as e:
            last_error = f'Error: {e}'
            time.sleep(delay)

    return (url, None, last_error)


def load_checkpoint(checkpoint_path):
    """Загружает существующий чекпоинт, если он есть."""
    if not os.path.exists(checkpoint_path):
        return None
    try:
        with open(checkpoint_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, OSError) as e:
        print(f'[Предупреждение] Не удалось загрузить чекпоинт {checkpoint_path}: {e}',
              file=sys.stderr)
        return None


def save_checkpoint(books, checkpoint_path, stats=None):
    """Сохраняет чекпоинт в JSON."""
    output_data = {
        'meta': {
            'total_books': len(books),
            'saved_at': datetime.now().isoformat(),
            'is_checkpoint': True,
        },
        'books': books,
    }
    if stats:
        output_data['meta'].update(stats)

    tmp_path = checkpoint_path + '.tmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, checkpoint_path)
        return True
    except OSError as e:
        print(f'[Ошибка] Не удалось сохранить чекпоинт: {e}', file=sys.stderr)
        try:
            with open(checkpoint_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            return True
        except OSError as e2:
            print(f'[Ошибка] И прямой вариант тоже не удался: {e2}', file=sys.stderr)
            return False


def save_final(books, output_path, stats=None):
    """Сохраняет финальный результат."""
    output_data = {
        'meta': {
            'total_books': len(books),
            'saved_at': datetime.now().isoformat(),
        },
        'books': books,
    }
    if stats:
        output_data['meta'].update(stats)

    tmp_path = output_path + '.tmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, output_path)
        return True
    except OSError as e:
        print(f'[Ошибка] Не удалось сохранить результат: {e}', file=sys.stderr)
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            return True
        except OSError as e2:
            print(f'[Ошибка] И прямой вариант тоже не удался: {e2}', file=sys.stderr)
            return False


def read_urls(file_path, start_line=None, end_line=None):
    """
    Читает URL из текстового файла (по одному на строку),
    с возможностью указать диапазон строк (1-based, включительно).

    Args:
        file_path (str): Путь к файлу.
        start_line (int, optional): Номер первой строки (1-based).
        end_line (int, optional): Номер последней строки (1-based, включительно).

    Returns:
        list: Список URL.
    """
    urls = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            if start_line is not None and line_num < start_line:
                continue
            if end_line is not None and line_num > end_line:
                break
            line = line.strip()
            if line and not line.startswith('#'):
                if not line.startswith('http'):
                    line = 'https://www.libex.ru' + line if line.startswith('/') else 'https://www.libex.ru/' + line
                urls.append(line)
    return urls


def get_processed_urls(checkpoint_path):
    """Возвращает множество уже обработанных URL из чекпоинта."""
    data = load_checkpoint(checkpoint_path)
    if data and 'books' in data:
        return {b.get('detail_url', '') for b in data['books'] if b.get('detail_url')}
    return set()



def process_books(
    input_path,
    output_path='libex_books_detail.json',
    threads=5,
    delay=REQUEST_DELAY,
    save_every=100,
    resume=False,
    verbose=True,
    failed_path=None,
    start_line=None,
    end_line=None,
):
    """
    Основная функция: читает URL, загружает и парсит детальные страницы.

    Args:
        input_path (str): Путь к файлу со списком URL.
        output_path (str): Путь к выходному JSON файлу.
        threads (int): Количество потоков.
        delay (float): Задержка между запросами (сек).
        save_every (int): Сохранять чекпоинт каждые N книг.
        resume (bool): Дозапись (пропустить уже загруженные).
        verbose (bool): Выводить прогресс.
        failed_path (str): Путь к файлу для неудачных URL.
        start_line (int, optional): Начальная строка в файле (1-based).
        end_line (int, optional): Конечная строка в файле (1-based, включительно).

    Returns:
        list: Список обработанных книг.
    """
    base, ext = os.path.splitext(output_path)
    checkpoint_path = f'{base}_checkpoint{ext or ".json"}'
    if failed_path is None:
        failed_path = f'{base}_failed.txt'

    all_urls = read_urls(input_path, start_line, end_line)
    total_urls = len(all_urls)

    if verbose:
        print(f'[Старт] Загружено URL: {total_urls}', file=sys.stderr)
        print(f'[Старт] Потоков: {threads}, задержка: {delay}с', file=sys.stderr)
        print(f'[Старт] Выходной файл: {output_path}', file=sys.stderr)
        print(f'[Старт] Чекпоинт: {checkpoint_path}', file=sys.stderr)

    processed_urls = set()
    existing_books = []
    if resume:
        checkpoint_data = load_checkpoint(checkpoint_path)
        if checkpoint_data and 'books' in checkpoint_data:
            existing_books = checkpoint_data['books']
            processed_urls = {b.get('detail_url', '') for b in existing_books if b.get('detail_url')}
            if verbose:
                print(f'[Resume] Найдено ранее обработанных: {len(existing_books)} книг',
                      file=sys.stderr)

    urls_to_process = [u for u in all_urls if u not in processed_urls]
    skipped = total_urls - len(urls_to_process)

    if verbose and skipped > 0:
        print(f'[Resume] Пропущено (уже обработано): {skipped} URL', file=sys.stderr)

    if not urls_to_process:
        if verbose:
            print('[Готово] Нет новых URL для обработки.', file=sys.stderr)
        return existing_books

    if verbose:
        print(f'[Старт] Осталось обработать: {len(urls_to_process)} URL', file=sys.stderr)

    all_books = list(existing_books)
    failed_urls = []
    processed_count = 0
    total_to_process = len(urls_to_process)
    stats = {
        'total_input_urls': total_urls,
        'skipped_existing': skipped,
        'processed_new': 0,
        'failed': 0,
    }

    start_time = time.time()

    with ThreadPoolExecutor(max_workers=threads) as executor:
        future_to_url = {
            executor.submit(fetch_and_parse, url, delay): url
            for url in urls_to_process
        }

        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                result_url, book, error = future.result()
            except Exception as e:
                result_url, book, error = url, None, f'Exception: {e}'

            processed_count += 1

            if book:
                all_books.append(book)
                if verbose:
                    title = book.get('title', book.get('title_from_title', '?'))
                    with _print_lock:
                        print(f'[{processed_count}/{total_to_process}] ✓ {title[:60]}',
                              file=sys.stderr)
            else:
                failed_urls.append(url)
                if verbose:
                    with _print_lock:
                        print(f'[{processed_count}/{total_to_process}] ✗ {url} — {error}',
                              file=sys.stderr)


            if save_every > 0 and len(all_books) - len(existing_books) > 0 and \
               (len(all_books) - len(existing_books)) % save_every == 0:
                stats['processed_new'] = len(all_books) - len(existing_books)
                stats['failed'] = len(failed_urls)
                stats['elapsed_sec'] = round(time.time() - start_time, 1)
                with _file_lock:
                    save_checkpoint(all_books, checkpoint_path, stats)
                    if failed_urls and failed_path:
                        with open(failed_path, 'w', encoding='utf-8') as f:
                            for fu in failed_urls:
                                f.write(fu + '\n')
                if verbose:
                    eta = ''
                    if processed_count > 0:
                        rate = processed_count / (time.time() - start_time)
                        remaining = total_to_process - processed_count
                        eta = f', ETA: {remaining / rate:.0f}с' if rate > 0 else ''
                    with _print_lock:
                        print(f'[Чекпоинт] Сохранено {len(all_books)} книг '
                              f'({processed_count}/{total_to_process}{eta})',
                              file=sys.stderr)

    stats['processed_new'] = len(all_books) - len(existing_books)
    stats['failed'] = len(failed_urls)
    stats['elapsed_sec'] = round(time.time() - start_time, 1)
    stats['total_processed'] = len(all_books)

    if verbose:
        print(f'\n[Финал] Обработано книг: {len(all_books)}', file=sys.stderr)
        print(f'[Финал] Успешно: {len(all_books) - len(existing_books)} новых', file=sys.stderr)
        print(f'[Финал] Ошибок: {len(failed_urls)}', file=sys.stderr)
        print(f'[Финал] Время: {stats["elapsed_sec"]}с', file=sys.stderr)

    save_final(all_books, output_path, stats)

    if failed_urls and failed_path:
        with open(failed_path, 'w', encoding='utf-8') as f:
            for fu in failed_urls:
                f.write(fu + '\n')
        if verbose:
            print(f'[Финал] Неудачные URL сохранены в: {failed_path}', file=sys.stderr)

    save_checkpoint(all_books, checkpoint_path, stats)

    if verbose:
        print(f'[Готово] Результат сохранён в: {output_path}', file=sys.stderr)

    return all_books



def main():
    parser = argparse.ArgumentParser(
        description='Воркер для скачивания детальной информации о книгах с Libex.ru',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  %(prog)s detail.txt --threads 10
  %(prog)s detail.txt --resume --output books_detail.json
  %(prog)s detail.txt --threads 20 --delay 0
  %(prog)s ссылки/detail1400str.txt -o detail1400.json --threads 15 --save-every 200
        """
    )

    parser.add_argument('input', nargs='?', default=None,
                        help='Путь к файлу со списком URL (по одному на строку)')
    parser.add_argument('-o', '--output', default='libex_books_detail.json',
                        help='Путь к выходному JSON файлу (по умолчанию: libex_books_detail.json)')
    parser.add_argument('--threads', type=int, default=5,
                        help='Количество потоков (по умолчанию: 5)')
    parser.add_argument('--delay', type=float, default=REQUEST_DELAY,
                        help=f'Задержка между запросами в секундах (по умолчанию: {REQUEST_DELAY})')
    parser.add_argument('--save-every', type=int, default=100,
                        help='Чекпоинт каждые N книг (по умолчанию: 100, 0 = отключить)')
    parser.add_argument('--resume', action='store_true',
                        help='Дозапись: пропустить уже обработанные URL')
    parser.add_argument('--failed', type=str, default=None,
                        help='Файл для неудачных URL (по умолчанию: <output>_failed.txt)')
    parser.add_argument('--quiet', action='store_true', help='Не выводить прогресс')
    parser.add_argument('--test', type=str, default=None, metavar='URL',
                        help='Режим теста: распарсить одну страницу и вывести результат')
    parser.add_argument('--start-line', type=int, default=None,
                        help='Номер первой строки из файла для обработки (1-based)')
    parser.add_argument('--end-line', type=int, default=None,
                        help='Номер последней строки из файла (1-based, включительно)')


    args = parser.parse_args()

    # Режим теста
    if args.test:
        print(f'[Тест] Загружаю: {args.test}')
        try:
            html = fetch_page(args.test)
            book = parse_detail_page(html, args.test)
            if book:
                print(json.dumps(book, ensure_ascii=False, indent=2))
            else:
                print('[Ошибка] Не удалось распарсить страницу')
        except Exception as e:
            print(f'[Ошибка] {e}')
        return

    if not os.path.exists(args.input):
        print(f'[Ошибка] Файл не найден: {args.input}', file=sys.stderr)
        sys.exit(1)

    process_books(
        input_path=args.input,
        output_path=args.output,
        threads=args.threads,
        delay=args.delay,
        save_every=args.save_every,
        resume=args.resume,
        verbose=not args.quiet,
        failed_path=args.failed,
        start_line=args.start_line,
        end_line=args.end_line,
    )


if __name__ == '__main__':
    main()


