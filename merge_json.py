"""
Объединяет все JSON-файлы из заданной папки в один JSON-файл.

Если JSON-файлы содержат списки, итоговый файл будет содержать один общий список.
Если файл содержит объект-обёртку вида {"meta": {...}, "books": [...]} (так пишут
libex_parser.py и libex_detail_worker.py), из него берётся массив книг, а обёртка
с "meta" отбрасывается — иначе весь чекпоинт попал бы в результат одной записью.
Для прочих объектов и значений старое поведение: объект добавляется как отдельный
элемент итогового списка. Распаковку можно отключить флагом --no-unwrap.

Дубликаты книг удаляются — так же, как в clean_json.py: по умолчанию по ISBN,
а для книг без ISBN только при полном совпадении четырёх полей
(название + автор + издательство + год). Записи без ISBN и без хотя бы одного
из этих четырёх полей не удаляются вообще. Файлы обрабатываются по алфавиту,
поэтому запись остаётся в первом файле, где она встретилась.

Ключ сравнения задаётся опцией -k/--dedup-key, дедупликацию можно отключить
флагом --no-dedup, отчёт об удалённых дублях пишется опцией -R.

Книги чистятся ещё и от лишних полей: удаляются те же ключи, что и в
clean_json.py (FIELDS_TO_REMOVE: detail_url, book_id, in_stock, format и т.д. —
функция remove_extra_fields() оттуда же). Чистка включена по умолчанию,
старое поведение (склеить как есть, поля не трогать) — флаг --no-clean-fields.

Примеры использования:

    python3 merge_json.py -i JSONS -o JSONS/merged_books.json -R dups.json


    python merge_json.py --input JSON --output merged_books.json
    python merge_json.py -i JSON -o merged_books.json
    python merge_json.py -i JSON -o merged_books.json --no-recursive
    python merge_json.py -i JSONS -o merged_books.json -k isbn
    python merge_json.py -i JSONS -o merged_books.json --no-dedup
    python merge_json.py -i JSONS -o merged_books.json --no-unwrap
    python merge_json.py -i JSONS -o merged_books.json --no-clean-fields
    python merge_json.py -i JSONS -o merged_books.json -R dups.json
"""

import argparse
import json
import sys
from pathlib import Path

# Дедупликация, распаковка обёрток и чистка полей — общие с clean_json.py:
# тот же ключ поиска дублей, тот же формат отчёта, те же ключи массива книг
# и тот же список удаляемых полей (FIELDS_TO_REMOVE / remove_extra_fields)
from clean_json import (
    BOOKS_KEYS,
    DEDUP_KEY_DEFAULT,
    DEDUP_KEY_HELP,
    FIELDS_TO_REMOVE,
    Deduplicator,
    dedup_key_type,
    remove_extra_fields,
    write_duplicates_report,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Объединить все JSON-файлы из папки в один файл.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # склеить папку и удалить дубли (ключ по умолчанию: 4 поля / ISBN)
  %(prog)s -i JSONS -o merged_books.json
  # то же + отчёт об удалённых дублях
  %(prog)s -i JSONS -o merged_books.json -R dups.json
  # только по ISBN, без учёта книг без ISBN
  %(prog)s -i JSONS -o merged_books.json -k isbn
  # просто склеить, дубликаты не удалять
  %(prog)s -i JSONS -o merged_books.json --no-dedup
  # склеить и оставить все поля как есть (без чистки от лишних полей)
  %(prog)s -i JSONS -o merged_books.json --no-clean-fields
        """,
    )
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        type=Path,
        help="Папка, в которой нужно искать JSON-файлы.",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        type=Path,
        help="Путь к итоговому JSON-файлу.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Искать JSON-файлы только в указанной папке, без вложенных папок.",
    )
    parser.add_argument(
        "-k",
        "--dedup-key",
        type=dedup_key_type,
        default=DEDUP_KEY_DEFAULT,
        metavar="КЛЮЧ",
        help=f"Ключ поиска дублей: {DEDUP_KEY_HELP}",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Не удалять дубликаты: просто склеить файлы (старое поведение).",
    )
    parser.add_argument(
        "--no-unwrap",
        action="store_true",
        help='Не распаковывать объекты-обёртки {"meta": ..., "books": [...]}: '
             "такой файл добавляется в результат одним элементом (старое поведение).",
    )
    parser.add_argument(
        "--no-clean-fields",
        action="store_true",
        help="Не удалять лишние поля у книг (старое поведение). "
             "По умолчанию удаляются те же поля, что и в clean_json.py: "
             f"{', '.join(FIELDS_TO_REMOVE)}.",
    )
    parser.add_argument(
        "-R",
        "--report-duplicates",
        default=None,
        metavar="ФАЙЛ",
        help="Записать отчёт об удалённых дублях в JSON файл.",
    )
    return parser.parse_args()


def collect_json_files(input_dir: Path, recursive: bool = True):
    """Найти все JSON-файлы в папке."""
    pattern = "**/*.json" if recursive else "*.json"
    return sorted(input_dir.glob(pattern))


def extract_items(data, unwrap=True):
    """Превращает содержимое JSON-файла в список записей.

    Возвращает (записи, была_ли_распакована_обёртка).
    Если unwrap=True и это объект-обёртка {"meta": ..., "books": [...]},
    берётся массив книг без обёртки (как в clean_json.py).
    """
    if isinstance(data, list):
        return data, False
    if unwrap and isinstance(data, dict):
        for key in BOOKS_KEYS:
            value = data.get(key)
            if isinstance(value, list):
                return value, True
    return [data], False


def merge_json_files(input_dir: Path, output_file: Path, recursive: bool = True,
                     deduplicator=None, exclude_files=None, unwrap=True,
                     clean_fields=True):
    """Объединить JSON-файлы в один общий список.

    Если передан deduplicator, дубликаты удаляются по всем файлам сразу:
    ключи из уже прочитанных файлов учитываются (файлы идут по алфавиту,
    поэтому запись остаётся в первом файле, где она встретилась).
    Если unwrap=True, у файлов-обёрток {"meta": ..., "books": [...]} берётся
    массив книг, а обёртка отбрасывается.
    Если clean_fields=True (по умолчанию), у книг удаляются лишние поля тем же
    списком FIELDS_TO_REMOVE и той же функцией remove_extra_fields(), что и в
    clean_json.py — в результат сразу попадают только нужные поля.
    exclude_files — дополнительные пути, которые не нужно читать
    (например, файл отчёта, лежащий в той же папке).

    Возвращает словарь со статистикой.
    """
    if not input_dir.exists():
        raise FileNotFoundError(f"Папка не найдена: {input_dir}")

    if not input_dir.is_dir():
        raise NotADirectoryError(f"Указанный путь не является папкой: {input_dir}")

    output_file = output_file.resolve()
    input_dir = input_dir.resolve()

    skip_files = {output_file}
    for extra_path in exclude_files or []:
        skip_files.add(Path(extra_path).resolve())

    json_files = [
        file_path
        for file_path in collect_json_files(input_dir, recursive=recursive)
        if file_path.resolve() not in skip_files
    ]

    if not json_files:
        raise FileNotFoundError(f"В папке не найдено JSON-файлов: {input_dir}")

    merged_data = []
    items_read = 0
    unwrapped_files = 0
    in_file_duplicates = 0
    cross_file_duplicates = 0
    fields_removed = 0

    for file_path in json_files:
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        items, was_unwrapped = extract_items(data, unwrap=unwrap)
        if was_unwrapped:
            unwrapped_files += 1
        items_read += len(items)

        if deduplicator is not None:
            items, removed_in_file, removed_cross_file = deduplicator.deduplicate(
                items, str(file_path),
            )
            in_file_duplicates += removed_in_file
            cross_file_duplicates += removed_cross_file

        # Чистка от лишних полей — общей функцией из clean_json.py.
        # Делается после дедупликации: удалённые дубли поля уже не считает.
        if clean_fields:
            items, removed_fields = remove_extra_fields(items, FIELDS_TO_REMOVE)
            fields_removed += removed_fields

        merged_data.extend(items)

    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(merged_data, file, ensure_ascii=False, indent=2)

    return {
        "files_count": len(json_files),
        "items_read": items_read,
        "items_count": len(merged_data),
        "unwrapped_files": unwrapped_files,
        "in_file_duplicates": in_file_duplicates,
        "cross_file_duplicates": cross_file_duplicates,
        "duplicates_removed": in_file_duplicates + cross_file_duplicates,
        "fields_removed": fields_removed,
        "cleaned_fields": clean_fields,
        "output": str(output_file),
        "dedup_key": deduplicator.dedup_key if deduplicator is not None else None,
    }


def main():
    args = parse_args()

    deduplicator = None
    if not args.no_dedup:
        deduplicator = Deduplicator(
            dedup_key=args.dedup_key,
            collect_report=bool(args.report_duplicates),
        )

    stats = merge_json_files(
        input_dir=args.input,
        output_file=args.output,
        recursive=not args.no_recursive,
        deduplicator=deduplicator,
        exclude_files=[args.report_duplicates] if args.report_duplicates else None,
        unwrap=not args.no_unwrap,
        clean_fields=not args.no_clean_fields,
    )

    print(f"Объединено файлов: {stats['files_count']}")
    print(f"Прочитано записей: {stats['items_read']}")
    if stats["unwrapped_files"]:
        print(f"Распаковано файлов-обёрток с meta: {stats['unwrapped_files']}")
    elif args.no_unwrap:
        print("Распаковка обёрток с meta отключена (--no-unwrap)")
    if deduplicator is None:
        print("Дедупликация отключена (--no-dedup)")
    else:
        print(f"Убрано дублей: {stats['duplicates_removed']} "
              f"(в файлах: {stats['in_file_duplicates']}, "
              f"из других файлов: {stats['cross_file_duplicates']}), "
              f"ключ: {stats['dedup_key']}")
    if stats["cleaned_fields"]:
        print(f"Удалено лишних полей: {stats['fields_removed']} "
              f"(список полей: {len(FIELDS_TO_REMOVE)}, как в clean_json.py)")
    else:
        print("Чистка полей отключена (--no-clean-fields)")
    print(f"Всего записей: {stats['items_count']}")
    print(f"Результат сохранен: {stats['output']}")

    if args.report_duplicates:
        if deduplicator is None:
            print("Флаг -R/--report-duplicates вместе с --no-dedup: "
                  "дубликаты не удалялись, отчёт не создаётся.", file=sys.stderr)
        elif write_duplicates_report(args.report_duplicates, args.dedup_key,
                                     deduplicator.removed):
            print(f"Отчёт об удалённых дублях: {args.report_duplicates} "
                  f"(записей: {len(deduplicator.removed)})")


if __name__ == "__main__":
    main()
