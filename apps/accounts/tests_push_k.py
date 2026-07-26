"""
Web Push подписки (новый код, тестов не было).

Проверяем изоляцию: подписка привязывается к текущему пользователю, чужую
подписку нельзя ни создать, ни удалить, даже зная её endpoint.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import PushSubscription, User
from apps.companies.models import Company

URL = '/api/v1/accounts/push/subscribe/'
BODY = {
    'endpoint': 'https://push.example.com/sub/abc123',
    'keys': {'p256dh': 'p256dh-value', 'auth': 'auth-value'},
}


class PushSubscriptionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='PushCo', is_active=True)
        self.alice = User.objects.create_user(username='push_alice', password='p',
                                              role=User.Role.WORKER, company=self.company)
        self.bob = User.objects.create_user(username='push_bob', password='p',
                                            role=User.Role.WORKER, company=self.company)

    def api(self, user=None):
        c = APIClient()
        if user:
            c.force_authenticate(user=user)
        return c

    def test_anonymous_cannot_subscribe(self):
        resp = self.api().post(URL, BODY, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_subscribe_binds_to_requesting_user_and_company(self):
        resp = self.api(self.alice).post(URL, BODY, format='json')
        self.assertEqual(resp.status_code, 201)
        sub = PushSubscription.objects.get()
        self.assertEqual(sub.user_id, self.alice.id)
        self.assertEqual(sub.company_id, self.company.id)
        self.assertTrue(sub.is_active)

    def test_repeat_subscribe_updates_not_duplicates(self):
        self.api(self.alice).post(URL, BODY, format='json')
        resp = self.api(self.alice).post(URL, BODY, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PushSubscription.objects.filter(user=self.alice).count(), 1)

    def test_missing_keys_rejected(self):
        resp = self.api(self.alice).post(URL, {'endpoint': BODY['endpoint']}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(PushSubscription.objects.exists())

    def test_user_cannot_delete_someone_elses_subscription(self):
        self.api(self.alice).post(URL, BODY, format='json')
        # Bob знает endpoint Alice и пытается его удалить.
        resp = self.api(self.bob).delete(URL, {'endpoint': BODY['endpoint']}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['deleted'])            # ничего не удалено
        self.assertTrue(PushSubscription.objects.filter(user=self.alice).exists())

    def test_user_can_delete_own_subscription(self):
        self.api(self.alice).post(URL, BODY, format='json')
        resp = self.api(self.alice).delete(URL, {'endpoint': BODY['endpoint']}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['deleted'])
        self.assertFalse(PushSubscription.objects.filter(user=self.alice).exists())

    def test_subscription_of_other_user_is_not_returned_or_overwritten(self):
        self.api(self.alice).post(URL, BODY, format='json')
        # Bob подписывается тем же endpoint: должна появиться ОТДЕЛЬНАЯ запись,
        # подписка Alice не должна быть перезаписана чужими ключами.
        bob_body = {'endpoint': BODY['endpoint'],
                    'keys': {'p256dh': 'bob-p256dh', 'auth': 'bob-auth'}}
        self.api(self.bob).post(URL, bob_body, format='json')
        alice_sub = PushSubscription.objects.get(user=self.alice)
        self.assertEqual(alice_sub.p256dh_key, 'p256dh-value')
        self.assertEqual(PushSubscription.objects.count(), 2)
