"""
Health-проба под production-настройками (аудит K + доводка под любой хостинг).

Внутренняя проба (docker healthcheck, k8s, балансировщик) опрашивает контейнер
обычным HTTP и без X-Forwarded-Proto. Два production-гарда мешали этому:
  1) Host не из ALLOWED_HOSTS -> DisallowedHost (400);
  2) SECURE_SSL_REDIRECT=True -> 301 на https.

(2) лечится точечным SECURE_REDIRECT_EXEMPT только для health — остальной
трафик по-прежнему уходит на HTTPS. (1) — переменной PRIVATE_HEALTH_HOST,
которую production.py добавляет в ALLOWED_HOSTS.
"""
from django.test import TestCase, override_settings

HEALTH = '/api/v1/core/health/'

PROD = dict(
    DEBUG=False,
    ALLOWED_HOSTS=['skladpro.example.com', 'healthcheck.internal'],
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
        # Так ходит внутренняя проба: обычный HTTP, свой Host, без
        # X-Forwarded-Proto. Раньше здесь был 301 -> контейнер «нездоров».
        resp = self.client.get(HEALTH, HTTP_HOST='healthcheck.internal')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'ok')

    def test_private_host_rejected_when_not_allowed(self):
        # Имя контейнера/сервиса, которого нет в ALLOWED_HOSTS и в
        # PRIVATE_HEALTH_HOST: Django отдаёт 400, проба считает контейнер
        # нездоровым, внешний прокси возвращает 502 при живом приложении.
        resp = self.client.get(HEALTH, HTTP_HOST='app-container.internal')
        self.assertEqual(resp.status_code, 400)

    def test_private_host_accepted_when_allowed(self):
        # PRIVATE_HEALTH_HOST добавляется в ALLOWED_HOSTS в production.py,
        # и тогда healthcheck по внутреннему имени проходит.
        with self.settings(ALLOWED_HOSTS=['app-container.internal']):
            resp = self.client.get(HEALTH, HTTP_HOST='app-container.internal')
            self.assertEqual(resp.status_code, 200)
