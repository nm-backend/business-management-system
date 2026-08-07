"""
WsTicket: чистка и лимит при выдаче.

GET /ws-ticket/ раньше плодил строку на КАЖДЫЙ вызов, а таблица WsTicket
нигде не чистилась (страница чата запрашивает тикет при каждом открытии).
Теперь при выдаче удаляются использованные/истёкшие/старые тикеты, а
одновременно активных остаётся не больше 5.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.messaging.models import WsTicket
from apps.messaging.services import issue_ws_ticket

URL = '/api/v1/messaging/ws-ticket/'


class WsTicketCleanupTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='WsCo', is_active=True)
        self.worker = User.objects.create_user(username='ws_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)

    def api(self):
        c = APIClient()
        c.force_authenticate(user=self.worker)
        return c

    def test_repeated_issue_caps_active_tickets(self):
        for _ in range(7):
            resp = self.api().get(URL)
            self.assertEqual(resp.status_code, 200)
        count = WsTicket.objects.filter(user=self.worker, used=False).count()
        self.assertLessEqual(count, 5)

    def test_used_tickets_are_cleaned_on_next_issue(self):
        issue_ws_ticket(self.worker)
        issue_ws_ticket(self.worker)
        WsTicket.objects.filter(user=self.worker).update(used=True)
        issue_ws_ticket(self.worker)
        left = WsTicket.objects.filter(user=self.worker).count()
        self.assertEqual(left, 1)

    def test_expired_tickets_are_cleaned_on_next_issue(self):
        old = WsTicket.objects.create(
            company=self.company, user=self.worker,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        issue_ws_ticket(self.worker)
        self.assertFalse(WsTicket.objects.filter(pk=old.pk).exists())

    def test_recently_issued_tickets_survive_within_cap(self):
        for _ in range(3):
            issue_ws_ticket(self.worker)
        self.assertEqual(WsTicket.objects.filter(user=self.worker).count(), 3)
