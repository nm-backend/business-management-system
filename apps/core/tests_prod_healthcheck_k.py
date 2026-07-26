"""
Health-проба под production-настройками (аудит K + доводка после Railway).

Оркестратор опрашивает контейнер изнутри обычным HTTP и без X-Forwarded-Proto.
Два гарда production мешали этому:
  1) Host не из ALLOWED_HOSTS -> DisallowedHost (400);
  2) SECURE_SSL_REDIRECT=True -> 301 на https.

(2) воспроизведён на боевом Railway: daphne слушал порт, но health отдавал 301,
и деплой падал с "1/1 replicas never became healthy!". Лечится точечным
SECURE_REDIRECT_EXEMPT только для health — остальной трафик по-прежнему на HTTPS.
"""
from django.test import TestCase, override_settings

HEALTH = '/api/v1/core/health/'

PROD = dict(
    DEBUG=False,
    ALLOWED_HOSTS=['skladpro.example.com', 'healthcheck.railway.app'],
    SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'),
    SECURE_REDIRECT_EXEMPT=[r'^api/v1/core/health/$'],
)


@override_settings(**PROD)
class ProdHealthcheckProbeTests(TestCase):
    def test_host_outside_allowed_hosts_rejected(self):
        # Host-защита остаётся: loopback-хост не в ALLOWED_HOSTS.
        resp = self.client.get(HEALTH, HTTP_HOST='127.0.0.1:8000')
        self.assertEqual(resp.status_code, 400)

    def test_plain_http_probe_without_forwarded_proto_returns_200(self):
        # Так ходит Railway: внутренний HTTP, свой Host, без X-Forwarded-Proto.
        # Раньше здесь был 301 -> деплой считался неудачным.
        resp = self.client.get(HEALTH, HTTP_HOST='healthcheck.railway.app')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'ok')

    def test_probe_with_forwarded_proto_still_ok(self):
        resp = self.client.get(HEALTH, HTTP_HOST='skladpro.example.com',
                               HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(resp.status_code, 200)

    def test_other_paths_are_still_https_redirected(self):
        # Исключение действует ТОЛЬКО на health: остальное форсится на HTTPS.
        resp = self.client.get('/api/v1/accounts/setup/check/',
                               HTTP_HOST='skladpro.example.com')
        self.assertEqual(resp.status_code, 301)
        self.assertTrue(resp['Location'].startswith('https://'))
