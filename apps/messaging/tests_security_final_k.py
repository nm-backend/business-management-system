"""
Финальная перепроверка аудита (этап 8): флаг can_see_other_workers
соблюдается в контактах и при старте личного диалога; сообщения ограничены
по длине; курс валют не принимает неположительные значения.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.core.models import Currency, ExchangeRate

EMPLOYEES = '/api/v1/messaging/employees/'
START_DIRECT = '/api/v1/messaging/conversations/start_direct/'
MESSAGES = '/api/v1/messaging/messages/'


class CanSeeOtherWorkersTests(TestCase):
    """Список контактов и старт диалога уважают флаг can_see_other_workers."""

    def setUp(self):
        self.company = Company.objects.create(name='CSOW', is_active=True)
        self.owner = User.objects.create_user(username='csow_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.admin_restricted = User.objects.create_user(
            username='csow_admin', password='p', role=User.Role.ADMIN,
            company=self.company, can_see_other_workers=False)
        self.admin_open = User.objects.create_user(
            username='csow_admin2', password='p', role=User.Role.ADMIN,
            company=self.company, can_see_other_workers=True)
        self.worker = User.objects.create_user(username='csow_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.worker2 = User.objects.create_user(username='csow_worker2', password='p',
                                                role=User.Role.WORKER, company=self.company)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _names(self, resp):
        rows = resp.data['results'] if isinstance(resp.data, dict) and 'results' in resp.data else resp.data
        return {row['username'] for row in rows}

    def test_owner_sees_everyone(self):
        resp = self.api(self.owner).get(EMPLOYEES)
        names = self._names(resp)
        self.assertIn('csow_admin', names)
        self.assertIn('csow_worker', names)

    def test_restricted_admin_does_not_see_workers(self):
        resp = self.api(self.admin_restricted).get(EMPLOYEES)
        names = self._names(resp)
        self.assertNotIn('csow_worker', names)
        self.assertNotIn('csow_worker2', names)
        self.assertIn('csow_owner', names)

    def test_open_admin_sees_workers(self):
        resp = self.api(self.admin_open).get(EMPLOYEES)
        self.assertIn('csow_worker', self._names(resp))

    def test_restricted_admin_cannot_start_dm_with_worker(self):
        resp = self.api(self.admin_restricted).post(
            START_DIRECT, {'user_id': self.worker.id}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_open_admin_can_start_dm_with_worker(self):
        resp = self.api(self.admin_open).post(
            START_DIRECT, {'user_id': self.worker.id}, format='json')
        self.assertEqual(resp.status_code, 200)

    def test_restricted_admin_can_start_dm_with_owner(self):
        resp = self.api(self.admin_restricted).post(
            START_DIRECT, {'user_id': self.owner.id}, format='json')
        self.assertEqual(resp.status_code, 200)


class MessageLengthTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='MSGLEN', is_active=True)
        self.user = User.objects.create_user(username='msglen_user', password='p',
                                             role=User.Role.OWNER, company=self.company)
        from apps.messaging.models import Conversation, ConversationParticipant
        self.conv = Conversation.objects.create(company=self.company,
                                                kind=Conversation.Kind.GENERAL)
        ConversationParticipant.objects.create(conversation=self.conv, user=self.user)

    def test_oversized_message_rejected(self):
        c = APIClient()
        c.force_authenticate(user=self.user)
        resp = c.post(MESSAGES, {
            'conversation': self.conv.id, 'content': 'x' * 10001,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_normal_message_accepted(self):
        c = APIClient()
        c.force_authenticate(user=self.user)
        resp = c.post(MESSAGES, {
            'conversation': self.conv.id, 'content': 'привет',
        }, format='json')
        self.assertEqual(resp.status_code, 201)


class ExchangeRateValidatorTests(TestCase):
    def test_zero_rate_rejected(self):
        cur = Currency.objects.create(code='USD', name='Доллар', symbol='$', is_default=True)
        rate = ExchangeRate(from_currency=cur, to_currency=cur,
                            rate=Decimal('0'), effective_date='2026-01-01')
        with self.assertRaises(ValidationError):
            rate.full_clean()

    def test_negative_rate_rejected(self):
        cur = Currency.objects.create(code='USD', name='Доллар', symbol='$', is_default=True)
        rate = ExchangeRate(from_currency=cur, to_currency=cur,
                            rate=Decimal('-1'), effective_date='2026-01-01')
        with self.assertRaises(ValidationError):
            rate.full_clean()

    def test_positive_rate_accepted(self):
        cur = Currency.objects.create(code='USD', name='Доллар', symbol='$', is_default=True)
        rate = ExchangeRate(from_currency=cur, to_currency=cur,
                            rate=Decimal('1.5'), effective_date='2026-01-01')
        rate.full_clean()
