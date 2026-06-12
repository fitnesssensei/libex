10000 stranic sparseno

# чистка JSON
python3 clean_json.py JSONS/230_cleaned.json


python3 libex_parser.py --online --max-pages 3
# Загрузить страницы 1-5
python3 libex_parser.py --online --page-range "1-5"
# Загрузить конкретные страницы 1, 3, 5
python3 libex_parser.py --online --page-range "1,3,5"
# Смешанный диапазон
python3 libex_parser.py --online --page-range "1-3,5,7-10"
# Все страницы (если есть локальный файл для определения total_pages)
python3 libex_parser.py --online --page-range "all" --input local_page.html
# С комбинацией других параметров
python3 libex_parser.py --online --page-range "1-10" --max-pages 5 --delay 2.0


## примеры с диапазоном 
# Обработать строки 100-200 из detail.txt (101 книга)
python3 libex_detail_worker.py detail.txt --start-line 100 --end-line 200 --threads 10
# Обработать первые 50 строк
python3 libex_detail_worker.py detail.txt --end-line 50 --threads 5
# Обработать с 500-й строки до конца файла
python3 libex_detail_worker.py detail.txt --start-line 500 --threads 10
# Большой файл: строки 5000-10000 из 14412
python3 libex_detail_worker.py ссылки/detail1400str.txt -o chunk_5k-10k.json \
  --start-line 5000 --end-line 10000 --threads 15 --save-every 200

## Примеры использования очистка JSON:
# Один файл → создаст JSONS/100_cleaned.json
python3 clean_json.py JSONS/100.json
# Изменить файл на месте (с бэкапом)
python3 clean_json.py JSONS/100.json --in-place --backup
# Обработать все JSON в директории
python3 clean_json.py json_fails/
# Рекурсивно обработать всё
python3 clean_json.py . --recursive --in-place --backup