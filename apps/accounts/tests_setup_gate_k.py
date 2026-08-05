"""
Заглушка первичной настройки (SetupGate).

Гонка первичной настройки: два параллельных POST /setup/owner/ с разными
username оба проходили проверку «суперадмина ещё нет» до коммита любого
из них — в системе появлялось два суперадмина. Теперь запрос сериализуется
через единственную строку SetupGate (SELECT ... FOR UPDATE на PostgreSQL).
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import SetupGate, User

SETUP_URL = '/api/v1/accounts/setup/owner/'

DATA = {
    'username': 'owner',
    'password': 'Skl4dPro!Nod',
    'password_confirm': 'Skl4dPro!Nod',
    'full_name': 'Owner',
}


class SetupGateTests(TestCase):
    def setUp(self):
        self.api = APIClient()

    def test_gate_row_exists_after_migrations(self):
        """Ровно одна строка заглушки создаётся миграцией."""
        self.assertEqual(SetupGate.objects.count(), 1)
        self.assertEqual(SetupGate.objects.get(pk=1).pk, 1)

    def test_second_setup_with_different_username_is_rejected(self):
        """Разные username больше не создают второго суперадмина."""
        first = self.api.post(SETUP_URL, DATA, format='json')
        self.assertEqual(first.status_code, 201)
        second = self.api.post(SETUP_URL, dict(DATA, username='owner2'), format='json')
        self.assertEqual(second.status_code, 403)
        self.assertEqual(User.objects.filter(role=User.Role.SUPERADMIN).count(), 1)

    def test_second_setup_with_same_username_is_rejected(self):
        """Повторный setup с тем же username — 400 (валидация) или 403, но не 500."""
        self.assertEqual(self.api.post(SETUP_URL, DATA, format='json').status_code, 201)
        resp = self.api.post(SETUP_URL, DATA, format='json')
        self.assertIn(resp.status_code, (400, 403))
        self.assertEqual(User.objects.filter(role=User.Role.SUPERADMIN).count(), 1)
