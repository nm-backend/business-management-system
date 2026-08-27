"""
Согласованность подписки: Company == billing.Subscription (проекция).

Company.subscription_status/start/end — единый источник истины для гейта и
жизненного цикла (grace-aware). billing.Subscription — проекция. Для КАЖДОГО
пути мутации подписки проверяем, что сроки совпадают, а статус проекции
соответствует статусу компании (с учётом того, что в billing-модели нет
отдельного статуса grace — он отражается как active).

Пути: создание (триал), extend/activate/set_end/freeze/unfreeze через
companies-API, extend/activate/freeze/unfreeze через billing-API и Celery
(active -> grace -> expired).
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.companies.tasks import auto_freeze_expired_subscriptions
from apps.companies.tests_subscriptions import make_admin, make_company, make_owner

from .models import Subscription

# Company status -> ожидаемый billing status (grace отражается как active).
STATUS_MAP = {
    Company.SubscriptionStatus.ACTIVE: 'active',
    Company.SubscriptionStatus.GRACE: 'active',
    Company.SubscriptionStatus.EXPIRED: 'expired',
    Company.SubscriptionStatus.FROZEN: 'frozen',
    Company.SubscriptionStatus.CANCELLED: 'frozen',
}


class SubscriptionConsistencyTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.company = make_company(name='ConsCo')
        self.owner = make_owner(self.company, username='cons_owner')
        make_admin(self.company, username='cons_admin')
        self.sub = Subscription.objects.get(company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(user=self.superadmin)

    def assert_consistent(self, expected_company_status=None):
        self.company.refresh_from_db()
        self.sub.refresh_from_db()
        # Сроки совпадают. Толерантность в 5 секунд — на сам сигнал создания
        # (billing) и триал компании два разных вызова timezone.now(): дрейф в
        # микросекунды — шум, а реальный дрейф (дни/часы) ловится строго.
        self.assertIsNotNone(self.sub.expires_at)
        self.assertIsNotNone(self.company.subscription_end)
        self.assertLess(
            abs(self.sub.expires_at - self.company.subscription_end),
            timedelta(seconds=5),
            'billing.expires_at расходится с company.subscription_end',
        )
        self.assertLess(
            abs(self.sub.started_at - self.company.subscription_start),
            timedelta(seconds=5),
            'billing.started_at расходится с company.subscription_start',
        )
        # Статус проекции соответствует статусу компании.
        self.assertEqual(
            self.sub.status,
            STATUS_MAP[self.company.subscription_status],
            'billing.status не соответствует company.subscription_status',
        )
        if expected_company_status is not None:
            self.assertEqual(self.company.subscription_status, expected_company_status)

    def test_trial_creation_consistent(self):
        self.assert_consistent(Company.SubscriptionStatus.ACTIVE)

    def test_companies_extend_consistent(self):
        resp = self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_extend/',
            {'days': 30}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assert_consistent(Company.SubscriptionStatus.ACTIVE)

    def test_companies_activate_consistent(self):
        self.company.subscription_status = Company.SubscriptionStatus.EXPIRED
        self.company.subscription_end = timezone.now() - timedelta(days=5)
        self.company.save(update_fields=['subscription_status', 'subscription_end'])
        resp = self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_activate/',
            {}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assert_consistent(Company.SubscriptionStatus.ACTIVE)

    def test_companies_set_end_consistent(self):
        end = timezone.now() + timedelta(days=45)
        resp = self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_set_end/',
            {'end': end.isoformat()}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assert_consistent(Company.SubscriptionStatus.ACTIVE)
        self.assertEqual(self.company.subscription_end, end)

    def test_companies_freeze_consistent(self):
        resp = self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_freeze/',
            {}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assert_consistent(Company.SubscriptionStatus.FROZEN)
        self.assertIsNotNone(self.sub.frozen_at)

    def test_companies_unfreeze_consistent(self):
        self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_freeze/',
            {}, format='json',
        )
        resp = self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_unfreeze/',
            {}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assert_consistent(Company.SubscriptionStatus.ACTIVE)
        self.assertIsNone(self.sub.frozen_at)

    def test_billing_extend_consistent(self):
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub.pk}/extend/',
            {'days': 30}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assert_consistent(Company.SubscriptionStatus.ACTIVE)

    def test_billing_activate_consistent(self):
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub.pk}/activate/',
            {'days': 30}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assert_consistent(Company.SubscriptionStatus.ACTIVE)

    def test_billing_freeze_consistent(self):
        # Ручная заморозка супер-админом — компания и проекция в FROZEN.
        self.company.subscription_status = Company.SubscriptionStatus.EXPIRED
        self.company.subscription_end = timezone.now() - timedelta(days=1)
        self.company.save(update_fields=['subscription_status', 'subscription_end'])
        Subscription.objects.filter(pk=self.sub.pk).update(
            status='expired', expires_at=self.company.subscription_end,
        )
        self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub.pk}/freeze/', {}, format='json',
        )
        # billing-заморозка синхронизирует компанию (обе в frozen).
        self.assert_consistent(Company.SubscriptionStatus.FROZEN)

    def test_celery_expire_to_grace_consistent(self):
        """active -> grace: проекция остаётся active, сроки совпадают."""
        end = timezone.now() - timedelta(days=1)
        Company.objects.filter(pk=self.company.pk).update(subscription_end=end)
        Subscription.objects.filter(pk=self.sub.pk).update(expires_at=end)
        auto_freeze_expired_subscriptions.run()
        self.assert_consistent(Company.SubscriptionStatus.GRACE)
        self.assertGreater(self.company.grace_end, timezone.now())

    def test_celery_expire_to_expired_consistent(self):
        """grace -> expired: проекция в expired, сроки совпадают."""
        end = timezone.now() - timedelta(days=8)
        Company.objects.filter(pk=self.company.pk).update(subscription_end=end)
        Subscription.objects.filter(pk=self.sub.pk).update(expires_at=end)
        auto_freeze_expired_subscriptions.run()
        self.assert_consistent(Company.SubscriptionStatus.EXPIRED)

    def test_grace_company_not_frozen_in_billing(self):
        """Не допускаем Company=GRACE при billing=FROZEN."""
        end = timezone.now() - timedelta(days=1)
        Company.objects.filter(pk=self.company.pk).update(subscription_end=end)
        Subscription.objects.filter(pk=self.sub.pk).update(expires_at=end)
        auto_freeze_expired_subscriptions.run()
        self.company.refresh_from_db()
        self.sub.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.GRACE)
        self.assertNotEqual(self.sub.status, 'frozen')
