"""
Health-эндпоинт не должен троттлиться (аудит K, доводка после стресс-теста).

Стресс показал: под флудом /health отдавал 429 (DRF UserRateThrottle 300/min по
IP). Оркестратор/LB бьёт health часто и 429 = ложный 'unhealthy' -> сорванный
деплой/рестарт. HealthView.throttle_classes = [] снимает троттлинг.
"""
from django.test import TestCase

from apps.core.views import HealthView


class HealthThrottleExemptTests(TestCase):
    def test_health_view_has_no_throttle_classes(self):
        self.assertEqual(HealthView.throttle_classes, [])

    def test_health_get_returns_200(self):
        resp = self.client.get('/api/v1/core/health/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'ok')
