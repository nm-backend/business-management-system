"""
Container healthcheck для web (Docker HEALTHCHECK / compose healthcheck).

Бьёт loopback http://127.0.0.1:8000/api/v1/core/health/, но под production-
настройками нужно обойти два гарда, которые иначе валят проверку:
  • ALLOWED_HOSTS: шлём Host = первый хост из ALLOWED_HOSTS (реальный домен),
    иначе DisallowedHost -> 400.
  • SECURE_SSL_REDIRECT: шлём X-Forwarded-Proto=https (production настроен
    SECURE_PROXY_SSL_HEADER), иначе http-запрос редиректится 301 на https.

Exit 0 = healthy (HTTP 200), иначе exit 1.
"""
import os
import sys
import urllib.request

host = (os.environ.get('ALLOWED_HOSTS', '') or '').split(',')[0].strip() or '127.0.0.1'
request = urllib.request.Request(
    'http://127.0.0.1:8000/api/v1/core/health/',
    headers={'Host': host, 'X-Forwarded-Proto': 'https'},
)
try:
    with urllib.request.urlopen(request, timeout=4) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
