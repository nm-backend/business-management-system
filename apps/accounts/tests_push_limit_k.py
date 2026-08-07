"""
PushSubscription: лимит 5 применяется только к НОВЫМ подпискам.

Раньше лимит проверялся ДО update_or_create: при заполненных 5 подписках
повторная регистрация уже существующего устройства (штатное обновление
ключей при каждом входе) отвечала 400, хотя новая строка не создалась бы.
Плюс проверка и вставка шли без блокировки — параллельные запросы могли
проскочить мимо лимита.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import PushSubscription, User
from apps.companies.models import Company

URL = '/api/v1/accounts/push/subscribe/'


def body(endpoint):
    return {'endpoint': endpoint, 'keys': {'p256dh': 'k' * 32, 'auth': 'a' * 16}}


class PushLimitTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='LimCo', is_active=True)
        self.worker = User.objects.create_user(username='lim_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)

    def api(self):
        c = APIClient()
        c.force_authenticate(user=self.worker)
        return c

    def _fill_to_limit(self):
        for i in range(5):
            resp = self.api().post(URL, body(f'https://push.example.com/d{i}'), format='json')
            self.assertEqual(resp.status_code, 201)

    def test_new_endpoint_after_limit_rejected(self):
        self._fill_to_limit()
        resp = self.api().post(URL, body('https://push.example.com/d-new'), format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(PushSubscription.objects.filter(user=self.worker).count(), 5)

    def test_resubscribe_existing_endpoint_at_limit_ok(self):
        self._fill_to_limit()
        resp = self.api().post(URL, body('https://push.example.com/d0'), format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PushSubscription.objects.filter(user=self.worker).count(), 5)

    def test_resubscribe_updates_keys(self):
        self.api().post(URL, body('https://push.example.com/d0'), format='json')
        new_keys = {'p256dh': 'z' * 32, 'auth': 'b' * 16}
        resp = self.api().post(URL, {
            'endpoint': 'https://push.example.com/d0', 'keys': new_keys,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        sub = PushSubscription.objects.get(user=self.worker)
        self.assertEqual(sub.p256dh_key, 'z' * 32)
        self.assertEqual(PushSubscription.objects.filter(user=self.worker).count(), 1)
