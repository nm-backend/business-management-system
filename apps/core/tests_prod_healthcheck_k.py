"""
Prod healthcheck probe (аудит K, находка #8).

Старый probe контейнера бил в http://127.0.0.1:8000/health под production-
настройками и всегда падал по двум причинам:
  1) Host=127.0.0.1 не в ALLOWED_HOSTS -> DisallowedHost (400);
  2) SECURE_SSL_REDIRECT=True + http без X-Forwarded-Proto -> 301 на https.
=> контейнер навсегда 'unhealthy'.

Правильный probe шлёт Host из ALLOWED_HOSTS и X-Forwarded-Proto=https
(production уже настроен SECURE_PROXY_SSL_HEADER) -> 200.
"""
from django.test import TestCase, override_settings

HEALTH = '/api/v1/core/health/'


@override_settings(
    DEBUG=False,
    ALLOWED_HOSTS=['skladpro.example.com'],
    SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'),
)
class ProdHealthcheckProbeTests(TestCase):
    def test_old_probe_loopback_host_rejected(self):
        # БАГ #1: Host=127.0.0.1 не в ALLOWED_HOSTS.
        resp = self.client.get(HEALTH, HTTP_HOST='127.0.0.1:8000')
        self.assertEqual(resp.status_code, 400)

    def test_old_probe_http_without_forwarded_proto_ssl_redirected(self):
        # БАГ #2: валидный Host, но http без X-Forwarded-Proto -> 301.
        resp = self.client.get(HEALTH, HTTP_HOST='skladpro.example.com')
        self.assertEqual(resp.status_code, 301)

    def test_new_probe_host_plus_forwarded_proto_ok(self):
        # ФИКС: Host из ALLOWED_HOSTS + X-Forwarded-Proto=https -> 200.
        resp = self.client.get(
            HEALTH, HTTP_HOST='skladpro.example.com',
            HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'ok')
