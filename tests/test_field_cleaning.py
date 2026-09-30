#!/usr/bin/env python3
"""Тесты чистки книг от лишних полей (clean_json.py + merge_json.py).

Проверяем:
  1) clean_book_item() / remove_extra_fields() — удаляют ровно заданные поля;
  2) clean_json_file() — старое поведение на месте: поля удаляются, обёртка
     {"meta": ..., "books": [...]} убирается, дубли внутри файла режутся;
  3) merge_json_files() — при склейке поля удаляются по умолчанию
     (та же функция и тот же список FIELDS_TO_REMOVE), а с clean_fields=False
     остаются (старое поведение);
  4) CLI merge_json.py — флаг --no-clean-fields сохраняет поля, по умолчанию чистит.

Тесты детерминированные: только временные папки, без сети и без sleep.
Запуск (из корня проекта):
    python3 -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Чтобы тесты работали и при запуске из любой папки — добавляем корень проекта
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import clean_json  # noqa: E402
import merge_json  # noqa: E402


# ── Вспомогательные данные ──

def book_a():
    """Книга с ISBN и четырьмя лишними полями."""
    return {
        "title": "Книга A", "author": "Иванов И.", "publisher": "АСТ",
        "year": 2001, "isbn": "978-5-17-000000-1", "pages": 100,
        "detail_url": "http://a", "book_id": 1, "in_stock": True,
        "image_thumb_url": "http://img",
    }


def book_a_dup():
    """Полный дубль книги A (тот же ISBN), отличается только лишними полями."""
    return {
        "title": "Книга A", "author": "Иванов И.", "publisher": "АСТ",
        "year": 2001, "isbn": "978-5-17-000000-1", "pages": 100,
        "detail_url": "http://a2", "book_id": 2,
    }


def book_b():
    """Книга без ISBN: дубль ищется по 4 полям."""
    return {
        "title": "Книга Б", "author": "Петров П.", "publisher": "Эксмо",
        "year": 2002, "isbn": None, "format": "pdf",
    }


def book_b_dup():
    """Дубль книги Б (4 поля совпадают), лежит в другом файле."""
    return {
        "title": "Книга Б", "author": "Петров П.", "publisher": "Эксмо",
        "year": 2002, "isbn": None, "category_url": "http://c",
    }


def book_c():
    """Новая книга с одним лишним полем."""
    return {
        "title": "Книга В", "author": "Сидоров С.", "publisher": "Питер",
        "year": 2003, "isbn": "978-5-4461-0000-2", "has_image": False,
    }


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

class FieldCleaningFunctionsTest(unittest.TestCase):
    """clean_book_item() и remove_extra_fields() из clean_json.py."""

    def test_clean_book_item_removes_only_listed_fields(self):
        item = book_a()
        removed = clean_json.clean_book_item(item)

        self.assertEqual(removed, 4)  # detail_url, book_id, in_stock, image_thumb_url
        for field in ("detail_url", "book_id", "in_stock", "image_thumb_url"):
            self.assertNotIn(field, item)
        # нужные поля остались нетронутыми
        self.assertEqual(item["title"], "Книга A")
        self.assertEqual(item["pages"], 100)

    def test_clean_book_item_skips_non_dict(self):
        # не-словарь не ломает чистку и не считается полем
        self.assertEqual(clean_json.clean_book_item("строка"), 0)
        self.assertEqual(clean_json.clean_book_item(None), 0)
        self.assertEqual(clean_json.clean_book_item([1, 2]), 0)

    def test_clean_book_item_uses_custom_field_list(self):
        item = {"title": "X", "format": "pdf", "book_id": 5}
        removed = clean_json.clean_book_item(item, fields=["book_id"])

        self.assertEqual(removed, 1)
        self.assertNotIn("book_id", item)
        self.assertIn("format", item)  # в свой список не входил — остался

    def test_remove_extra_fields_counts_all_books(self):
        books = [book_a(), "мусор", book_b(), {"title": "без лишних полей"}]
        cleaned, removed = clean_json.remove_extra_fields(books, clean_json.FIELDS_TO_REMOVE)

        self.assertIs(cleaned, books)      # список чистится на месте
        self.assertEqual(removed, 5)       # 4 у A + 1 (format) у Б
        self.assertNotIn("format", cleaned[2])
        self.assertEqual(cleaned[1], "мусор")  # не-словарь не тронут

    def test_remove_extra_fields_tolerates_non_list(self):
        value, removed = clean_json.remove_extra_fields({"title": "не список"})
        self.assertEqual(removed, 0)
        self.assertEqual(value, {"title": "не список"})


class CleanJsonFileRegressionTest(unittest.TestCase):
    """Старое поведение clean_json_file() должно сохраниться."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "a.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_fields_removed_meta_stripped_and_dedup_in_file(self):
        write_json(self.path, {"meta": {"parsed": 3}, "books": [book_a(), book_a_dup()]})

        result = clean_json.clean_json_file(str(self.path), in_place=True, backup=True)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["removed_count"], 6)          # 4 у A + 2 у дубля A
        self.assertEqual(result["duplicates_removed"], 1)
        self.assertEqual(result["books_count"], 1)
        self.assertTrue(result["meta_removed"])
        self.assertEqual(result["meta_keys_removed"], ["meta"])

        data = read_json(self.path)
        self.assertIsInstance(data, list)                     # обёртка убрана
        self.assertNotIn("detail_url", data[0])
        self.assertEqual(data[0]["pages"], 100)

        backup = read_json(Path(result["backup"]))
        self.assertIn("meta", backup)                         # в бэкапе всё как было
        self.assertIn("detail_url", backup["books"][0])


class MergeFieldsCleaningTest(unittest.TestCase):
    """merge_json_files(): склейка + чистка полей."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write_json(self.dir / "a.json",
                   {"meta": {"parsed": 3}, "books": [book_a(), book_a_dup(), book_b()]})
        write_json(self.dir / "b.json", [book_b_dup(), book_c()])

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_cleans_fields_and_keeps_dedup_and_unwrap(self):
        out = self.dir / "merged.json"
        dedup = clean_json.Deduplicator(dedup_key=clean_json.DEDUP_KEY_DEFAULT)

        stats = merge_json.merge_json_files(self.dir, out, deduplicator=dedup)

        self.assertEqual(stats["files_count"], 2)
        self.assertEqual(stats["items_read"], 5)               # 3 + 2
        self.assertEqual(stats["unwrapped_files"], 1)          # a.json был обёрткой
        self.assertEqual(stats["in_file_duplicates"], 1)       # дубль A внутри a.json
        self.assertEqual(stats["cross_file_duplicates"], 1)    # Б из b.json
        self.assertEqual(stats["items_count"], 3)              # A, Б, В
        self.assertTrue(stats["cleaned_fields"])
        # A: detail_url, book_id, in_stock, image_thumb_url; Б: format; В: has_image
        self.assertEqual(stats["fields_removed"], 6)

        merged = read_json(out)
        self.assertIsInstance(merged, list)                     # обёртки в итоге нет
        self.assertEqual(len(merged), 3)
        for book in merged:
            for field in clean_json.FIELDS_TO_REMOVE:
                self.assertNotIn(field, book)
        self.assertEqual(sorted(merged[0].keys()),
                         ["author", "isbn", "pages", "publisher", "title", "year"])

    def test_no_clean_fields_keeps_everything(self):
        out = self.dir / "merged_raw.json"
        dedup = clean_json.Deduplicator(dedup_key=clean_json.DEDUP_KEY_DEFAULT)

        stats = merge_json.merge_json_files(self.dir, out, deduplicator=dedup,
                                            clean_fields=False)

        self.assertFalse(stats["cleaned_fields"])
        self.assertEqual(stats["fields_removed"], 0)

        merged = read_json(out)
        self.assertEqual(len(merged), 3)
        self.assertIn("detail_url", merged[0])                  # лишние поля на месте
        self.assertIn("book_id", merged[0])


class MergeCliTest(unittest.TestCase):
    """CLI merge_json.py: --no-clean-fields и чистка по умолчанию."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write_json(self.dir / "a.json", [book_a()])

    def tearDown(self):
        self.tmp.cleanup()

    def _run_main(self, *extra_args):
        out = self.dir / "out.json"
        argv = ["merge_json.py", "-i", str(self.dir), "-o", str(out), *extra_args]
        buffer = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buffer):
            merge_json.main()
        return out, buffer.getvalue()

    def test_cli_cleans_fields_by_default(self):
        out, text = self._run_main()

        self.assertIn("Удалено лишних полей: 4", text)
        self.assertNotIn("detail_url", read_json(out)[0])

    def test_cli_no_clean_fields_keeps_fields(self):
        out, text = self._run_main("--no-clean-fields")

        self.assertIn("Чистка полей отключена (--no-clean-fields)", text)
        self.assertIn("detail_url", read_json(out)[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)

