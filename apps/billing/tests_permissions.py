"""
Права и изоляция (IDOR) billing-эндпоинтов.

  - владелец видит ТОЛЬКО подписку своей компании;
  - работник/админ не могут управлять подпиской;
  - список всех подписок и все изменяющие операции — только супер-админ;
  - владелец не может продлить/заморозить/подтвердить счёт чужой компании.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company

from .models import Invoice, Subscription
from .services import create_invoice


class BillingPermissionTests(TestCase):
    def setUp(self):
        self.company_a, self.owner_a = self._company('AlphaB')
        self.company_b, self.owner_b = self._company('BetaB')
        self.worker_a = User.objects.create_user(
            username='alpha_worker', password='pw',
            role=User.Role.WORKER, company=self.company_a,
        )
        self.admin_a = User.objects.create_user(
            username='alpha_admin', password='pw',
            role=User.Role.ADMIN, company=self.company_a,
        )
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.sub_a = Subscription.objects.get(company=self.company_a)
        self.sub_b = Subscription.objects.get(company=self.company_b)
        self.api = APIClient()

    @staticmethod
    def _company(name):
        company = Company.objects.create(name=name)
        owner = User.objects.create_user(
            username=f'{name}_owner', password='pw', role=User.Role.OWNER, company=company,
        )
        return company, owner

    def test_owner_sees_only_own_subscription(self):
        self.api.force_authenticate(user=self.owner_a)
        resp = self.api.get('/api/v1/billing/subscription/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['company'], self.company_a.id)
        self.assertEqual(resp.data['id'], self.sub_a.id)

    def test_worker_and_admin_cannot_manage_subscription(self):
        for user in (self.worker_a, self.admin_a):
            self.api.force_authenticate(user=user)
            self.assertEqual(
                self.api.get('/api/v1/billing/subscription/').status_code, 403,
            )
            self.assertEqual(
                self.api.post('/api/v1/billing/subscription/renew/', {}, format='json').status_code,
                403,
            )

    def test_owner_cannot_list_all_subscriptions(self):
        self.api.force_authenticate(user=self.owner_a)
        self.assertEqual(self.api.get('/api/v1/billing/subscriptions/').status_code, 403)

    def test_superadmin_lists_all_subscriptions(self):
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.get('/api/v1/billing/subscriptions/')
        self.assertEqual(resp.status_code, 200)
        ids = [row['id'] for row in resp.data['results']]
        self.assertIn(self.sub_a.id, ids)
        self.assertIn(self.sub_b.id, ids)

    def test_superadmin_can_search_by_company(self):
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.get('/api/v1/billing/subscriptions/?search=Beta')
        self.assertEqual(resp.status_code, 200)
        ids = [row['id'] for row in resp.data['results']]
        self.assertNotIn(self.sub_a.id, ids)
        self.assertIn(self.sub_b.id, ids)

    def test_owner_cannot_modify_own_subscription_via_admin_api(self):
        # Изменяющие операции подписок — только супер-админ.
        self.api.force_authenticate(user=self.owner_a)
        for action, body in [
            ('extend', {'days': 30}),
            ('activate', {}),
            ('freeze', {}),
            ('unfreeze', {}),
            ('confirm_payment', {'invoice_id': 1}),
        ]:
            resp = self.api.post(
                f'/api/v1/billing/subscriptions/{self.sub_a.id}/{action}/',
                body, format='json',
            )
            self.assertEqual(resp.status_code, 403, action)

    def test_owner_cannot_extend_other_company(self):
        self.api.force_authenticate(user=self.owner_a)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub_b.id}/extend/',
            {'days': 30}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_owner_cannot_confirm_invoice_of_other_company(self):
        # Счёт компании B создан её владельцем; владелец A пытается его оплатить.
        invoice, _ = create_invoice(self.sub_b, actor=self.owner_b)
        self.api.force_authenticate(user=self.owner_a)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub_b.id}/confirm_payment/',
            {'invoice_id': invoice.id}, format='json',
        )
        self.assertEqual(resp.status_code, 403)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PENDING)

    def test_admin_api_rejects_unknown_invoice_for_subscription(self):
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub_a.id}/confirm_payment/',
            {'invoice_id': 999999}, format='json',
        )
        self.assertEqual(resp.status_code, 404)

    def test_extend_requires_valid_days(self):
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub_a.id}/extend/',
            {'days': 0}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub_a.id}/extend/',
            {'days': 366}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_superadmin_is_not_affected_by_subscription_gate(self):
        # Супер-админ не привязан к компании — gate его не трогает (а
        # бизнес-данные ему закрыты IsCompanyMember, это другой механизм).
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.get('/api/v1/warehouse/raw-materials/')
        self.assertEqual(resp.status_code, 403)
        self.assertNotEqual(resp.data.get('code'), 'subscription_expired')
