"""
Сводка непрочитанных чата для панели администратора.

«Ишчилар мулоқазалари» — сумма непрочитанных в личных диалогах с работниками.
Общий чат и диалоги с владельцем туда не входят. Чужой tenant не светится.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.messaging.models import ChatMessage
from apps.messaging.services import get_or_create_direct

SUMMARY = '/api/v1/messaging/conversations/unread_summary/'


class UnreadSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='UnreadCo')
        cls.owner = User.objects.create_user(
            username='us_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='us_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
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

    def test_from_workers_counts_direct_unread_from_workers(self):
        self._message(self.worker, self.admin, 'задача готова')
        self._message(self.worker, self.admin, 'и ещё')
        self._message(self.owner, self.admin, 'от хозяина')
        data = self.api_as(self.admin).get(SUMMARY).data
        self.assertEqual(data['from_workers'], 2)
        self.assertEqual(data['total'], 3)

    def test_read_conversation_drops_from_workers(self):
        conv = self._message(self.worker, self.admin)
        before = self.api_as(self.admin).get(SUMMARY).data
        self.assertEqual(before['from_workers'], 1)
        self.api_as(self.admin).post(f'/api/v1/messaging/conversations/{conv.id}/read/')
        after = self.api_as(self.admin).get(SUMMARY).data
        self.assertEqual(after['from_workers'], 0)

    def test_other_company_not_counted(self):
        self._message(self.other_worker, self.other_admin)
        data = self.api_as(self.admin).get(SUMMARY).data
        self.assertEqual(data['from_workers'], 0)
        self.assertEqual(data['total'], 0)

    def test_worker_can_read_own_summary(self):
        self._message(self.admin, self.worker)
        data = self.api_as(self.worker).get(SUMMARY).data
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['from_workers'], 0)
