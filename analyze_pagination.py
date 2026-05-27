#!/usr/bin/env python3
"""Скрипт для детального анализа структуры пагинации на libex.ru"""
import re
from urllib.request import urlopen, Request, build_opener, install_opener, HTTPCookieProcessor
from http.cookiejar import CookieJar

cookie_jar = CookieJar()
opener = build_opener(HTTPCookieProcessor(cookie_jar))
install_opener(opener)

headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
    'Referer': 'https://www.libex.ru/',
    'Connection': 'keep-alive',
}

def fetch_page(url):
    req = Request(url, headers=headers)
    return urlopen(req).read().decode('cp1251')

# Init session
urlopen(Request('https://www.libex.ru/', headers=headers)).read()

# Fetch pages 1 (pg=0), 2 (pg=1), 10 (pg=9), 11 (pg=10)
for pg_num in [0, 1, 9, 10]:
    if pg_num == 0:
        url = 'https://www.libex.ru/cat/fiction/'
    else:
        url = f'https://www.libex.ru/cat/fiction/?pg={pg_num}'
    
    content = fetch_page(url)
    
    print(f'=== PAGE pg={pg_num} ===')
    
    # Find all TD page links
    tds = re.findall(r'<td[^>]*><a href="\?pg=(\d+)">(\d+)</a></td>', content)
    print(f'  Page TDs: {sorted(set(tds))}')
    
    # Find image navigation
    nav_imgs = re.findall(r'<a href="\?pg=(\d+)"><img[^>]+alt="([^"]+)"', content)
    print(f'  Nav images: {nav_imgs}')
    
    # Find selected/current page
    sel = re.search(r'<td class="selected"><a href="\?pg=(\d+)">(\d+)</a></td>', content)
    if sel:
        print(f'  Selected: pg={sel.group(1)}, page={sel.group(2)}')
    
    # Find the pagination section using "Страницы" or "страниц"
    for word in ['Страницы', 'страниц']:
        idx = content.find(word)
        if idx > -1:
            start = max(0, idx-200)
            end = min(len(content), idx+1000)
            table_end = content.find('</table>', idx)
            if table_end > 0 and table_end < end:
                end = table_end + 8
            snippet = content[start:end]
            print(f'  Context around "{word}":')
            print(snippet[:500])
            print('...')
            print(snippet[-200:])
            break
    
    print()

