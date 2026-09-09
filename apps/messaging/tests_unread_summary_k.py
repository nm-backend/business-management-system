"""
Непрочитанные от работников на панели администратора.

Нового messaging-эндпоинта нет: карточка считает сумму unread_count
по GET /messaging/conversations/, где kind=direct и other_user.role=worker.
Общий чат и диалоги с хозяином туда не входят. Чужой tenant не светится.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.messaging.models import ChatMessage
from apps.messaging.services import get_or_create_direct

LIST = '/api/v1/messaging/conversations/'


class WorkerUnreadFromConversationListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='UnreadCo')
        cls.owner = User.objects.create_user(
            username='us_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='us_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
            can_see_other_workers=True,
        )
        cls.worker = User.objects.create_user(
            username='us_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.other = Company.objects.create(name='OtherUnreadCo')
        cls.other_worker = User.objects.create_user(
            username='us_other_worker', password='pw', role=User.Role.WORKER,
            company=cls.other,
        )
        cls.other_admin = User.objects.create_user(
            username='us_other_admin', password='pw', role=User.Role.ADMIN,
            company=cls.other,
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def _message(self, sender, recipient, text='ping'):
        conv, _ = get_or_create_direct(sender.company, sender, recipient)
        ChatMessage.objects.create(
            company=sender.company, conversation=conv, sender=sender, content=text,
        )
        return conv

    def _counts(self, user):
        payload = self.api_as(user).get(LIST).data
        rows = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        total = 0
        from_workers = 0
        for conv in rows:
            unread = conv.get('unread_count') or 0
            total += unread
            other = conv.get('other_user') or {}
            if conv.get('kind') == 'direct' and other.get('role') == 'worker':
                from_workers += unread
        return total, from_workers

    def test_from_workers_counts_direct_unread_from_workers(self):
        self._message(self.worker, self.admin, 'задача готова')
        self._message(self.worker, self.admin, 'и ещё')
        self._message(self.owner, self.admin, 'от хозяина')
        total, from_workers = self._counts(self.admin)
        self.assertEqual(from_workers, 2)
        self.assertEqual(total, 3)

    def test_read_conversation_drops_from_workers(self):
        conv = self._message(self.worker, self.admin)
        _, before = self._counts(self.admin)
        self.assertEqual(before, 1)
        self.api_as(self.admin).post(f'/api/v1/messaging/conversations/{conv.id}/read/')
        _, after = self._counts(self.admin)
        self.assertEqual(after, 0)

    def test_other_company_not_counted(self):
        self._message(self.other_worker, self.other_admin)
        total, from_workers = self._counts(self.admin)
        self.assertEqual(from_workers, 0)
        self.assertEqual(total, 0)

    def test_no_unread_summary_endpoint(self):
        response = self.api_as(self.admin).get(f'{LIST}unread_summary/')
        self.assertEqual(response.status_code, 404)
