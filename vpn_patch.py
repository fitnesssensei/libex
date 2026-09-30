#!/usr/bin/env python3
"""
vpn_patch.py — патч для Python socket / urllib при работе через OpenVPN.

Загружается перед основным скриптом через механизм runpy (через ./vpn-run).
Делает три вещи:
  1. Форсирует IPv4 в socket.create_connection.
     Нужно, если DNS возвращает IPv6-адрес первым, а OpenVPN
     не маршрутизирует IPv6, из-за чего Python висит на таймауте.
  2. Устанавливает минимальный таймаут соединения 60 секунд.
     Переопределяет любой timeout меньше 60с — скрипты с
     REQUEST_TIMEOUT=20 будут работать с запасом.
  3. Добавляет retry (3 попытки) при URLError / socket.timeout.
"""

import socket
import time
import sys

# ──────────────────────────────────────────────
# 1. Принудительный IPv4 в create_connection
# ──────────────────────────────────────────────
_orig_create_connection = socket.create_connection

def _vpn_create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                           source_address=None, **kwargs):
    host, port = address
    if isinstance(host, str):
        # Резолвим ТОЛЬКО IPv4 (AF_INET)
        infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        if not infos:
            raise OSError(f"[vpn_patch] Не удалось разрешить {host} в IPv4")
        family, type_, proto, canonname, sockaddr = infos[0]

        sock = socket.socket(family, type_, proto)

        # Применяем таймаут: минимум 60 секунд
        if timeout is None or timeout == socket._GLOBAL_DEFAULT_TIMEOUT:
            sock.settimeout(None)
        else:
            sock.settimeout(max(timeout, 60))

        if source_address:
            sock.bind(source_address)
        sock.connect(sockaddr)
        return sock

    return _orig_create_connection(address, timeout, source_address, **kwargs)

socket.create_connection = _vpn_create_connection


# ──────────────────────────────────────────────
# 2. Retry при socket.timeout для urllib.urlopen
# ──────────────────────────────────────────────
import urllib.request
import urllib.error

_orig_urlopen = urllib.request.urlopen

def _vpn_urlopen(*args, **kwargs):
    """Обёртка urlopen с retry — пробрасывает все аргументы как есть."""
    max_retries = 3
    last_exc = None

    for attempt in range(max_retries):
        try:
            return _orig_urlopen(*args, **kwargs)
        except (urllib.error.URLError, socket.timeout, OSError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                wait = 2 ** attempt  # 1, 2, 4 секунды
                print(f"[vpn_patch] Таймаут/ошибка, попытка {attempt + 2}/{max_retries}"
                      f" через {wait}с: {exc}", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"[vpn_patch] Все {max_retries} попыток исчерпаны: {exc}",
                      file=sys.stderr)
                raise

urllib.request.urlopen = _vpn_urlopen


# ──────────────────────────────────────────────
# 3. Информация о применённом патче
# ──────────────────────────────────────────────
if __name__ == '__main__':
    # При прямом запуске ничего не делаем
    pass
else:
    print("[vpn_patch] Патч загружен: IPv4 + timeout ≥60с + retry 3×",
          file=sys.stderr)
