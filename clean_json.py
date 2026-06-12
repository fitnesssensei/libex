#!/usr/bin/env python3
"""
Скрипт для удаления указанных полей из JSON файлов Libex.

Удаляет заданные ключи из каждого объекта в массиве "books"
JSON-файлов формата: {"meta": {...}, "books": [...]}

Использование:
    # Один файл
    python clean_json.py json_fails/libex_books.json

    # Все JSON файлы в директории
    python clean_json.py json_fails/

    # С созданием бэкапа
    python clean_json.py json_fails/libex_books.json --backup

    # Изменение файла на месте (без создания _cleaned копии)
    python clean_json.py json_fails/libex_books.json --in-place
"""

import json
import os
import sys
import shutil
import argparse
from pathlib import Path


# Поля для удаления из каждой книги
FIELDS_TO_REMOVE = [
    "detail_url",
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


def normalize_isbn(isbn):
    if isbn is None:
        return None
    if not isinstance(isbn, str):
        isbn = str(isbn)
    normalized = ''.join(ch for ch in isbn.strip().upper() if ch not in ' -')
    return normalized or None


def get_isbn_key(item):
    if not isinstance(item, dict):
        return None
    return normalize_isbn(item.get('isbn'))


def deduplicate_books_by_isbn(books):
    seen_isbns = set()
    deduplicated_books = []
    duplicates_removed = 0

    for item in books:
        isbn_key = get_isbn_key(item)
        if isbn_key is None:
            deduplicated_books.append(item)
            continue
        if isbn_key in seen_isbns:
            duplicates_removed += 1
            continue
        seen_isbns.add(isbn_key)
        deduplicated_books.append(item)

    return deduplicated_books, duplicates_removed



def clean_json_file(filepath, in_place=False, backup=False):
    result = {
        'file': filepath,
        'removed_count': 0,
        'books_count': 0,
        'status': 'ok',
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
        for key in ('books', 'items', 'data'):
            if key in data and data[key] is books:
                books_key = key
                break
    elif isinstance(data, list):
        books = data
    else:
        result['status'] = 'Файл не является JSON-объектом или массивом'
        return result
    if books is None:
        result['status'] = 'Не найден массив books/items/data'
        return result
    if not isinstance(books, list):
        result['status'] = 'Поле books не является массивом'
        return result

    result['books_count'] = len(books)
    total_removed = 0
    for item in books:
        if not isinstance(item, dict):
            continue
        for field in FIELDS_TO_REMOVE:
            if field in item:
                del item[field]
                total_removed += 1

    books, duplicates_removed = deduplicate_books_by_isbn(books)
    result['books_count'] = len(books)
    result['duplicates_removed'] = duplicates_removed
    result['removed_count'] = total_removed

    if books_key is not None:
        data[books_key] = books
    else:
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


def process_path(path, in_place=False, backup=False, recursive=False):
    results = []
    target = Path(path)
    if target.is_file():
        if target.suffix.lower() == '.json':
            res = clean_json_file(str(target), in_place=in_place, backup=backup)
            results.append(res)
        else:
            print(f"Пропущен (не JSON): {target}", file=sys.stderr)
    elif target.is_dir():
        pattern = '**/*.json' if recursive else '*.json'
        for json_file in sorted(target.glob(pattern)):
            res = clean_json_file(str(json_file), in_place=in_place, backup=backup)
            results.append(res)
    else:
        print(f"Путь не найден: {path}", file=sys.stderr)
    return results


def main():
    parser = argparse.ArgumentParser(
        description='Удаление указанных полей из JSON файлов Libex',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  %(prog)s libex_books.json
  %(prog)s json_fails/ --in-place
  %(prog)s JSONS/100.json --backup --in-place
  %(prog)s . --recursive --backup
        """,
    )
    parser.add_argument('input', help='Путь к JSON файлу или директории')
    parser.add_argument('-i', '--in-place', action='store_true',
                        help='Изменять файл на месте')
    parser.add_argument('-b', '--backup', action='store_true',
                        help='Создавать .bak бэкап (с --in-place)')
    parser.add_argument('-r', '--recursive', action='store_true',
                        help='Рекурсивный поиск JSON в директориях')
    args = parser.parse_args()
    results = process_path(
        path=args.input, in_place=args.in_place,
        backup=args.backup, recursive=args.recursive,
    )
    if not results:
        print("Не найдено JSON файлов для обработки.", file=sys.stderr)
        sys.exit(1)
    print(f"\n{'='*60}")
    print(f"Обработано файлов: {len(results)}")
    print(f"{'='*60}")
    total_books = 0
    total_removed = 0
    total_duplicates_removed = 0
    errors = 0
    for res in results:
        status_icon = '✓' if res['status'] == 'ok' else '✗'
        parts = [f"  {status_icon} {res['file']}"]
        if res['books_count']:
            parts.append(f"книг: {res['books_count']}")
        if res['removed_count']:
            parts.append(f"удалено полей: {res['removed_count']}")
        if res.get('duplicates_removed'):
            parts.append(f"убрано дублей: {res['duplicates_removed']}")
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
    print(f"{'='*60}")
    print(f"Итого: {total_books} книг, удалено {total_removed} полей, убрано дублей: {total_duplicates_removed}")
    if errors:
        print(f"Ошибок: {errors}", file=sys.stderr)
    print(f"{'='*60}")
    if errors:
        sys.exit(1)


if __name__ == '__main__':
    main()
