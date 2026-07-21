"""
Этап D — health-check эндпоинт (production-readiness).

GET /api/v1/core/health/ должен быть публичным (без токена) и возвращать 200 с
{"status":"ok","database":true}, когда БД доступна. Используется Docker
healthcheck / балансировщиком.
"""
from django.test import TestCase
from rest_framework.test import APIClient


class HealthEndpointTests(TestCase):
    def test_health_ok_without_auth(self):
        resp = APIClient().get('/api/v1/core/health/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['status'], 'ok')
        self.assertTrue(body['database'])

    def test_health_exposes_no_sensitive_data(self):
        body = APIClient().get('/api/v1/core/health/').json()
        # Только статус и флаг БД — никаких имён/версий/секретов.
        self.assertEqual(set(body.keys()), {'status', 'database'})
