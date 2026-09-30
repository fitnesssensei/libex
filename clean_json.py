#!/usr/bin/env python3
"""
Скрипт для удаления указанных полей и дубликатов из JSON файлов Libex.

Удаляет заданные ключи из каждого объекта в массиве "books"
JSON-файлов формата: {"meta": {...}, "books": [...]}

Дубликаты книг удаляются не только внутри каждого файла, но и между всеми
файлами обрабатываемой папки: если книга уже была в другом файле, то из
текущего файла она удаляется. Файлы обрабатываются по алфавиту, поэтому
запись остаётся в первом файле (по порядку сортировки), где она встретилась.
Если нужно старое поведение (только внутри файла) — флаг --per-file.

Ключ поиска дублей задаётся опцией --dedup-key (-k):
    4 (по умолчанию) — по ISBN, а для книг без ISBN только при полном
            совпадении четырёх полей:
            название + автор + издательство + год;
    isbn    — только по ISBN (как в первых версиях скрипта).
Записи без ISBN, у которых нет хотя бы одного из четырёх полей
(название, автор, издательство, год), не удаляются вообще.

JSON-файлы, в которых нет массива книг (например, отчёты или служебные файлы),
в папке просто пропускаются — прогон из-за них не падает.

Служебная обёртка формата {"meta": {...}, "books": [...]} удаляется: блок
"meta" и все остальные ключи верхнего уровня отбрасываются, в файл пишется
чистый массив книг (как в уже очищенных файлах JSONS/, vBaze/). Флаг
--keep-meta сохраняет старое поведение — файл записывается целиком с "meta".

Чистка книг от лишних полей вынесена в отдельные функции clean_book_item() и
remove_extra_fields() (список полей — FIELDS_TO_REMOVE). Их же вызывает
merge_json.py, поэтому набор удаляемых полей один и тот же у обоих скриптов.

Использование (коротко):
    # одна общая команда: несколько папок сразу, дубли ищутся и между ними,
    # 4 поля по умолчанию, перезапись на месте с бэкапом и отчётом
    python clean_json.py vBaze/ JSONS/ -a -R dups.json

Подробные примеры:
    # Один файл (результат в файл *_clean.json, оригинал не меняется)
    python clean_json.py json_fails/libex_books.json

    # Все JSON файлы в директории (дубли между файлами тоже удаляются)
    python clean_json.py json_fails/

    # Перезаписать на месте с бэкапом (--apply = --in-place --backup)
    python clean_json.py json_fails/ -a

    # Дедупликация только внутри каждого файла (старое поведение)
    python clean_json.py json_fails/ --per-file

    # Только по ISBN, без учёта книг без ISBN
    python clean_json.py JSONS/ -k isbn -a

    # Оставить служебный блок "meta" в файле (старое поведение)
    python clean_json.py ссылки/ -a --keep-meta

    # Отчёт об удалённых дублях + пропуск уже очищенных файлов
    python clean_json.py JSONS/ -a -R duplicates.json -x "*_clean.json"

    # Рекурсивно, без создания _clean копий
    python clean_json.py . --recursive -a
"""

import fnmatch
import json
import os
import sys
import shutil
import argparse
from pathlib import Path


# Поля для удаления из каждой книги
FIELDS_TO_REMOVE = [
    "detail_url",
    "format",
    "book_id",
    "title_from_title",
    "author_from_title",
    "author_key",
    "meta_description",
    "category_path",
    "category_urls",
    "category_url",
    "author_search_url",
    "date_added",
    "image_thumb_url",
    "image_large_url",
    "has_image",
    "view_counter_id",
    "in_stock",
    "in_stock_text",
    "prev_book_url",
    "next_book_url",
]


def clean_book_item(item, fields=None):
    """Удаляет лишние поля из одной книги (словаря).

    Возвращает число удалённых полей. Записи, которые не являются словарём
    (например, строка или число в разнородном списке), не трогаются — как и
    раньше в clean_json_file(). Список полей берётся из FIELDS_TO_REMOVE,
    но его можно передать аргументом fields (свой набор полей).
    """
    if not isinstance(item, dict):
        return 0
    if fields is None:
        fields = FIELDS_TO_REMOVE
    removed = 0
    for field in fields:
        if field in item:
            del item[field]
            removed += 1
    return removed


def remove_extra_fields(books, fields=None):
    """Чистит список книг от лишних полей (та же логика, что была в clean_json_file).

    Возвращает (список книг, сколько полей удалено). Список меняется на месте,
    поэтому он же и возвращается: удобно писать books, removed = remove_extra_fields(books).
    Функция общая: её использует и clean_json.py, и merge_json.py (склейка JSON),
    чтобы чистка полей была в одном месте и не расходилась между скриптами.
    """
    if not isinstance(books, list):
        return books, 0
    removed = 0
    for item in books:
        removed += clean_book_item(item, fields=fields)
    return books, removed


# Ключи верхнего уровня, в которых может лежать массив книг
BOOKS_KEYS = ('books', 'items', 'data')


# Режимы поиска дублей для опции -k/--dedup-key
KEY_FOUR_FIELDS = 'title-author-publisher-year'
DEDUP_KEY_DEFAULT = KEY_FOUR_FIELDS
# Короткие и длинные варианты названий режимов
DEDUP_KEY_ALIASES = {
    '4': KEY_FOUR_FIELDS,
    '4fields': KEY_FOUR_FIELDS,
    KEY_FOUR_FIELDS: KEY_FOUR_FIELDS,
    'isbn': 'isbn',
}
DEDUP_KEY_HELP = ('4 — название+автор+издательство+год для книг без ISBN '
                  f'(по умолчанию, {KEY_FOUR_FIELDS}); isbn — только по ISBN')


def normalize_isbn(isbn):
    if isbn is None:
        return None
    if not isinstance(isbn, str):
        isbn = str(isbn)
    normalized = ''.join(ch for ch in isbn.strip().upper() if ch not in ' -')
    return normalized or None


def normalize_text(value):
    """Приводит текстовое поле к виду, пригодному для сравнения."""
    if value is None:
        return ''
    if not isinstance(value, str):
        value = str(value)
    return ' '.join(value.split()).casefold()


def get_dedup_key(item, dedup_key='isbn'):
    """Ключ книги для поиска дублей.

    Возвращает кортеж-ключ либо None, если запись сравнивать нельзя
    (нет ISBN в режиме isbn; нет названия, автора, издательства или года
    в режиме title-author-publisher-year).
    """
    if not isinstance(item, dict):
        return None

    isbn = normalize_isbn(item.get('isbn'))
    if isbn:
        return ('isbn', isbn)
    if dedup_key == 'isbn':
        return None

    if dedup_key == KEY_FOUR_FIELDS:
        title = normalize_text(item.get('title'))
        author = normalize_text(item.get('author'))
        publisher = normalize_text(item.get('publisher'))
        year = normalize_text(item.get('year'))
        # Для книг без ISBN дублем считаем только полное совпадение
        # всех четырёх полей: название + автор + издательство + год.
        if not title or not author or not publisher or not year:
            return None
        return (KEY_FOUR_FIELDS, title, author, publisher, year)

    return None


class Deduplicator:
    """Удаляет дубликаты книг внутри файла и между файлами одной папки.

    Ключи книг из уже обработанных файлов хранятся в состоянии объекта,
    поэтому книга, найденная в другом файле, считается дубликатом.
    Порядок файлов задаёт «победителя»: запись остаётся в первом файле.
    """

    def __init__(self, dedup_key='isbn', cross_file=True, collect_report=False):
        self.dedup_key = dedup_key
        self.cross_file = cross_file
        self.collect_report = collect_report
        self.seen_before = set()   # ключи из ранее обработанных файлов
        self.removed = []          # краткий отчёт об удалённых дублях

    def deduplicate(self, books, filepath):
        """Возвращает (книги без дублей, удалено в файле, удалено как дубли других файлов)."""
        kept = []
        keys_this_file = set()
        in_file_removed = 0
        cross_file_removed = 0

        for item in books:
            key = get_dedup_key(item, self.dedup_key)
            if key is None:
                kept.append(item)
                continue
            if key in keys_this_file:
                in_file_removed += 1
                self._remember(item, filepath, key, 'дубль внутри файла')
                continue
            keys_this_file.add(key)
            if self.cross_file and key in self.seen_before:
                cross_file_removed += 1
                self._remember(item, filepath, key, 'дубль из другого файла')
                continue
            kept.append(item)

        if self.cross_file:
            self.seen_before.update(keys_this_file)

        return kept, in_file_removed, cross_file_removed

    def _remember(self, item, filepath, key, reason):
        if not self.collect_report:
            return
        self.removed.append({
            'file': filepath,
            'reason': reason,
            'key': list(key),
            'title': item.get('title'),
            'author': item.get('author'),
            'publisher': item.get('publisher'),
            'year': item.get('year'),
            'isbn': item.get('isbn'),
        })



def clean_json_file(filepath, in_place=False, backup=False, deduplicator=None,
                    keep_meta=False):
    result = {
        'file': filepath,
        'removed_count': 0,
        'books_count': 0,
        'status': 'ok',
        'meta_removed': False,
        'meta_keys_removed': [],
    }
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        result['status'] = f'Ошибка чтения: {e}'
        return result
    books_key = None
    if isinstance(data, dict):
        books = data.get('books', data.get('items', data.get('data', None)))
        for key in BOOKS_KEYS:
            if key in data and data[key] is books:
                books_key = key
                break
    elif isinstance(data, list):
        books = data
    else:
        result['skipped'] = 'Файл не является JSON-объектом или массивом'
        return result
    if books is None:
        result['skipped'] = 'Не найден массив books/items/data'
        return result
    if not isinstance(books, list):
        result['skipped'] = 'Поле books не является массивом'
        return result

    result['books_count'] = len(books)
    # Чистим книги от лишних полей общей функцией (её же использует merge_json.py)
    books, total_removed = remove_extra_fields(books, FIELDS_TO_REMOVE)

    if deduplicator is None:
        deduplicator = Deduplicator()
    books, duplicates_removed, cross_file_duplicates_removed = deduplicator.deduplicate(
        books, filepath,
    )
    result['books_count'] = len(books)
    result['duplicates_removed'] = duplicates_removed
    result['cross_file_duplicates_removed'] = cross_file_duplicates_removed
    result['removed_count'] = total_removed

    if keep_meta and books_key is not None:
        # старое поведение: файл сохраняется целиком вместе с "meta"
        data[books_key] = books
    else:
        if books_key is not None:
            # убираем служебную обёртку: "meta" и остальные ключи верхнего уровня
            result['meta_removed'] = True
            result['meta_keys_removed'] = [k for k in data if k != books_key]
        data = books
    if in_place:
        if backup:
            backup_path = filepath + '.bak'
            try:
                shutil.copy2(filepath, backup_path)
                result['backup'] = backup_path
            except IOError as e:
                result['status'] = f'Ошибка создания бэкапа: {e}'
                return result
        output_path = filepath
    else:
        base, ext = os.path.splitext(filepath)
        output_path = f"{base}_clean{ext}"
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        result['output'] = output_path
    except IOError as e:
        result['status'] = f'Ошибка записи: {e}'
        return result
    return result


def is_excluded(filepath, patterns):
    """Проверяет путь по шаблонам --exclude (fnmatch по имени файла и по пути)."""
    if not patterns:
        return False
    path = Path(filepath)
    return any(
        fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(str(path), pattern)
        for pattern in patterns
    )


def collect_json_files(path, recursive=False, exclude=None):
    """Список JSON файлов для одного пути (файл или папка), по алфавиту."""
    target = Path(path)
    exclude = list(exclude or [])
    if target.is_file():
        if target.suffix.lower() != '.json':
            print(f"Пропущен (не JSON): {target}", file=sys.stderr)
            return []
        if is_excluded(target, exclude):
            print(f"Пропущен (исключён): {target}", file=sys.stderr)
            return []
        return [target]
    if target.is_dir():
        pattern = '**/*.json' if recursive else '*.json'
        files = []
        for json_file in sorted(target.glob(pattern)):
            if is_excluded(json_file, exclude):
                print(f"Пропущен (исключён): {json_file}", file=sys.stderr)
                continue
            files.append(json_file)
        return files
    print(f"Путь не найден: {path}", file=sys.stderr)
    return []


def process_paths(paths, in_place=False, backup=False, recursive=False,
                  deduplicator=None, exclude=None, keep_meta=False):
    """Обрабатывает все указанные пути: файлы и папки, в заданном порядке.

    Дубликаты удаляются не только внутри каждого файла, но и между всеми
    файлами всех указанных путей: ключи книг хранятся в одном Deduplicator.
    Один и тот же файл, попавший в список дважды, обрабатывается лишь раз.
    Служебная обёртка {"meta": ..., "books": [...]} убирается, если
    keep_meta=False (по умолчанию).
    """
    if deduplicator is None:
        deduplicator = Deduplicator()
    results = []
    processed_files = set()
    for path in paths:
        for json_file in collect_json_files(path, recursive=recursive, exclude=exclude):
            real_path = os.path.realpath(json_file)
            if real_path in processed_files:
                print(f"Пропущен (уже обработан): {json_file}", file=sys.stderr)
                continue
            processed_files.add(real_path)
            results.append(clean_json_file(
                str(json_file), in_place=in_place, backup=backup,
                deduplicator=deduplicator, keep_meta=keep_meta,
            ))
    return results


def process_path(path, in_place=False, backup=False, recursive=False,
                 deduplicator=None, exclude=None, keep_meta=False):
    """Обработка одного пути (совместимость: один файл или папка)."""
    return process_paths(
        [path], in_place=in_place, backup=backup, recursive=recursive,
        deduplicator=deduplicator, exclude=exclude, keep_meta=keep_meta,
    )


def dedup_key_type(value):
    """Принимает '4'/'4fields'/'title-author-publisher-year' или 'isbn'."""
    key = DEDUP_KEY_ALIASES.get(value.strip().lower())
    if key is None:
        raise argparse.ArgumentTypeError(
            f"неизвестный ключ дедупликации: {value!r} "
            f"(доступно: {', '.join(sorted(DEDUP_KEY_ALIASES))})"
        )
    return key


def parse_args():
    parser = argparse.ArgumentParser(
        description='Удаление указанных полей и дубликатов из JSON файлов Libex',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # одна общая команда: несколько папок сразу, дубли ищутся и между ними,
  # 4 поля по умолчанию, перезапись на месте с бэкапом и отчётом
  %(prog)s vBaze/ JSONS/ -a -R dups.json
  %(prog)s libex_books.json
  %(prog)s json_fails/ -a
  %(prog)s JSONS/ -k isbn -a
  %(prog)s ссылки/ -a --keep-meta
  %(prog)s . --recursive -a -x "*_clean.json"
        """,
    )
    parser.add_argument('input', nargs='+',
                        help='Путь к JSON файлу или директории (можно несколько)')
    parser.add_argument('-a', '--apply', action='store_true',
                        help='Применить на месте с бэкапом (= --in-place --backup)')
    parser.add_argument('-i', '--in-place', action='store_true',
                        help='Изменять файл на месте')
    parser.add_argument('-b', '--backup', action='store_true',
                        help='Создавать .bak бэкап (с --in-place/--apply)')
    parser.add_argument('-r', '--recursive', action='store_true',
                        help='Рекурсивный поиск JSON в директориях')
    parser.add_argument('-k', '--dedup-key', type=dedup_key_type, default=DEDUP_KEY_DEFAULT,
                        metavar='КЛЮЧ', help=f'Ключ поиска дублей: {DEDUP_KEY_HELP}')
    parser.add_argument('--keep-meta', action='store_true',
                        help='Не удалять служебную обёртку {"meta": ..., "books": [...]}: '
                             'файл записывается целиком (по умолчанию "meta" удаляется, '
                             'на выходе чистый массив книг)')
    parser.add_argument('--per-file', action='store_true',
                        help='Искать дубли только внутри каждого файла '
                             '(без учёта остальных файлов)')
    parser.add_argument('-x', '--exclude', action='append', default=[], metavar='ПАТТЕРН',
                        help='Пропустить файлы по шаблону (можно указывать несколько раз), '
                             'например: -x "*_clean.json"')
    parser.add_argument('-R', '--report-duplicates', default=None, metavar='ФАЙЛ',
                        help='Записать отчёт об удалённых дублях в JSON файл')
    return parser.parse_args()


def write_duplicates_report(report_path, dedup_key, removed):
    """Записывает отчёт об удалённых дублях в JSON файл."""
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump({
                'dedup_key': dedup_key,
                'total': len(removed),
                'duplicates': removed,
            }, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"Не удалось записать отчёт: {e}", file=sys.stderr)
        return False
    return True


def main():
    args = parse_args()
    in_place = args.in_place or args.apply
    backup = args.backup or args.apply
    if args.backup and not in_place:
        print("Флаг --backup без --in-place/--apply: бэкапы создаваться не будут.",
              file=sys.stderr)
    deduplicator = Deduplicator(
        dedup_key=args.dedup_key,
        cross_file=not args.per_file,
        collect_report=bool(args.report_duplicates),
    )
    exclude = list(args.exclude)
    if args.report_duplicates:
        # отчёт не должен попасть в обработку, если он лежит в одной из папок
        exclude.append(Path(args.report_duplicates).name)

    results = process_paths(
        paths=args.input, in_place=in_place,
        backup=backup, recursive=args.recursive,
        deduplicator=deduplicator, exclude=exclude,
        keep_meta=args.keep_meta,
    )
    if not results:
        print("Не найдено JSON файлов для обработки.", file=sys.stderr)
        sys.exit(1)
    scope = 'только внутри файла' if args.per_file else 'по всем указанным файлам'
    print(f"\n{'='*60}")
    print(f"Путей: {len(args.input)} | файлов к обработке: {len(results)} | "
          f"дедупликация: {scope} | ключ: {args.dedup_key}")
    print(f"{'='*60}")
    total_books = 0
    total_removed = 0
    total_duplicates_removed = 0
    total_cross_file_removed = 0
    meta_removed_files = 0
    skipped = 0
    errors = 0
    for res in results:
        if res.get('skipped'):
            # не список книг (например, отчёт или служебный JSON) — просто пропускаем
            print(f"  – {res['file']} | пропущен: {res['skipped']}")
            skipped += 1
            continue
        status_icon = '✓' if res['status'] == 'ok' else '✗'
        parts = [f"  {status_icon} {res['file']}"]
        if res['books_count']:
            parts.append(f"книг: {res['books_count']}")
        if res['removed_count']:
            parts.append(f"удалено полей: {res['removed_count']}")
        if res.get('duplicates_removed'):
            parts.append(f"убрано дублей в файле: {res['duplicates_removed']}")
        if res.get('cross_file_duplicates_removed'):
            parts.append(f"дублей из других файлов: {res['cross_file_duplicates_removed']}")
        if res.get('meta_removed'):
            parts.append("убрано meta: " + ', '.join(res['meta_keys_removed']))
        if res.get('output'):
            parts.append(f"→ {res['output']}")
        if res.get('backup'):
            parts.append(f"бэкап: {res['backup']}")
        print(' | '.join(parts))
        if res['status'] != 'ok':
            print(f"      Ошибка: {res['status']}")
            errors += 1
        total_books += res['books_count']
        total_removed += res['removed_count']
        total_duplicates_removed += res.get('duplicates_removed', 0)
        total_cross_file_removed += res.get('cross_file_duplicates_removed', 0)
        if res.get('meta_removed'):
            meta_removed_files += 1
    print(f"{'='*60}")
    print(f"Обработано файлов: {len(results) - skipped}")
    print(f"Итого: {total_books} книг, удалено {total_removed} полей")
    print(f"Убрано дублей: {total_duplicates_removed + total_cross_file_removed} "
          f"(в файлах: {total_duplicates_removed}, из других файлов: {total_cross_file_removed})")
    if args.keep_meta:
        print("Служебный блок meta не удалялся (--keep-meta)")
    else:
        print(f"Убрано обёрток с meta: {meta_removed_files} файлов")
    if skipped:
        print(f"Пропущено файлов (не список книг): {skipped}")
    if errors:
        print(f"Ошибок: {errors}", file=sys.stderr)
    print(f"{'='*60}")
    if args.report_duplicates and write_duplicates_report(
            args.report_duplicates, args.dedup_key, deduplicator.removed):
        print(f"Отчёт об удалённых дублях: {args.report_duplicates} "
              f"(записей: {len(deduplicator.removed)})")
    if errors:
        sys.exit(1)


if __name__ == '__main__':
    main()
