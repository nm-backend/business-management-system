"""
Согласованность двух моделей подписки (Company-поля и billing.Subscription).

Подписка описана двумя моделями: полями на Company (источник состояния) и
apps.billing.Subscription (счета, события, экран владельца). Эти тесты
гарантируют, что любое изменение через companies-сервис (продление, активация,
заморозка, разморозка, установка срока, смена тарифа, льготный период,
истечение) синхронизирует billing.Subscription, а subscription gate блокирует
компанию только по реальному состоянию — не по устаревшей billing-записи.

РЕГРЕССИЯ (воспроизведена): супер-админ продлевает компанию через companies-API
(/companies/{id}/subscription_extend/ — путь кнопки «Одобрить продление» в
сообщениях). billing.Subscription оставалась истёкшей, и gate по запасному
пути блокировал уже продлённую компанию (403 subscription_expired), хотя
Company.is_subscription_active был True.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company, SubscriptionPlan
from apps.companies.subscriptions import (
    activate_for_new_company,
    activate_subscription,
    change_plan,
    expire_company,
    extend_subscription,
    freeze_company,
    set_subscription_end,
    start_grace,
    unfreeze_company,
)
from apps.warehouse.models import RawMaterial

from .gate import _is_blocked
from .models import Subscription, SubscriptionEvent


class DualSourceSubscriptionTests(TestCase):
    """Поля Company — источник состояния; billing.Subscription — его зеркало."""

    def setUp(self):
        self.company = Company.objects.create(name='DualCo')
        activate_for_new_company(self.company)
        self.sub = Subscription.objects.get(company=self.company)
        self.owner = User.objects.create_user(
            username='dual_o', password='pw', role=User.Role.OWNER,
            company=self.company,
        )
        self.api = APIClient()

    def _login(self, user):
        resp = self.api.post('/api/v1/accounts/login/', {
            'username': user.username, 'password': 'pw', 'fingerprint': 'x' * 32,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data['tokens']['access']

    def _expire_both(self):
        """Переводит обе модели в состояние «срок истёк, льготный период вышел»."""
        past = timezone.now() - timedelta(days=10)
        Company.objects.filter(pk=self.company.pk).update(
            subscription_end=past, grace_period_days=0,
        )
        self.company.refresh_from_db()
        Subscription.objects.filter(pk=self.sub.pk).update(
            expires_at=past,
            status=Subscription.Status.ACTIVE,
        )
        self.sub.refresh_from_db()

    def test_company_creation_syncs_billing(self):
        sub = Subscription.objects.get(company=self.company)
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(sub.expires_at, self.company.subscription_end)

    def test_extend_via_companies_syncs_billing_and_unblocks_gate(self):
        # РЕГРЕССИЯ: продление через companies-API оставляло billing-запись
        # истёкшей, и gate блокировал продлённую компанию.
        self._expire_both()
        self.assertTrue(_is_blocked(self.company)[0])

        extend_subscription(self.company, days=30, actor=None, note='renewal approved')

        self.company.refresh_from_db()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(self.sub.expires_at, self.company.subscription_end)
        self.assertFalse(_is_blocked(self.company)[0], 'продлённая компания заблокирована')
        self.assertTrue(self.company.is_subscription_active)
        self.assertIsNotNone(self.sub.last_renewed_at)
        self.assertTrue(SubscriptionEvent.objects.filter(
            subscription=self.sub, action=SubscriptionEvent.Action.EXTENDED,
        ).exists())

    def test_business_api_works_after_companies_renewal(self):
        # Сквозная проверка: после продления реальный бизнес-запрос проходит.
        self._expire_both()
        extend_subscription(self.company, days=30)
        token = self._login(self.owner)
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        resp = self.api.get('/api/v1/warehouse/raw-materials/')
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_activate_syncs_billing(self):
        self._expire_both()
        activate_subscription(self.company)
        self.company.refresh_from_db()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(self.sub.expires_at, self.company.subscription_end)
        self.assertFalse(_is_blocked(self.company)[0])

    def test_set_end_syncs_billing(self):
        new_end = timezone.now() + timedelta(days=60)
        set_subscription_end(self.company, end=new_end)
        self.company.refresh_from_db()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(self.sub.expires_at, new_end)
        self.assertFalse(_is_blocked(self.company)[0])

    def test_freeze_syncs_billing_and_blocks(self):
        freeze_company(self.company)
        self.company.refresh_from_db()
        self.sub.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.FROZEN)
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)
        self.assertIsNotNone(self.sub.frozen_at)
        self.assertTrue(_is_blocked(self.company)[0])
        self.assertTrue(SubscriptionEvent.objects.filter(
            subscription=self.sub, action=SubscriptionEvent.Action.FROZEN,
        ).exists())

    def test_unfreeze_syncs_billing_and_unblocks(self):
        freeze_company(self.company)
        unfreeze_company(self.company)
        self.company.refresh_from_db()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertIsNone(self.sub.frozen_at)
        self.assertFalse(_is_blocked(self.company)[0])
        self.assertTrue(SubscriptionEvent.objects.filter(
            subscription=self.sub, action=SubscriptionEvent.Action.UNFROZEN,
        ).exists())

    def test_grace_keeps_company_unblocked_until_grace_end(self):
        # Истечение срока при ненулевом льготном периоде: бизнес работает,
        # billing-запись отражает фактический момент блокировки (grace_end).
        Company.objects.filter(pk=self.company.pk).update(
            subscription_end=timezone.now() - timedelta(days=1),
            grace_period_days=3,
        )
        self.company.refresh_from_db()
        start_grace(self.company)
        self.company.refresh_from_db()
        self.sub.refresh_from_db()

        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.GRACE)
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(self.sub.expires_at, self.company.grace_end)
        self.assertFalse(_is_blocked(self.company)[0], 'в льготный период компания должна работать')

        # После конца льготного периода — блокировка.
        Company.objects.filter(pk=self.company.pk).update(
            subscription_end=timezone.now() - timedelta(days=5),
        )
        self.company.refresh_from_db()
        expire_company(self.company)
        self.company.refresh_from_db()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.EXPIRED)
        self.assertTrue(_is_blocked(self.company)[0])

    def test_expire_syncs_billing(self):
        Company.objects.filter(pk=self.company.pk).update(
            subscription_end=timezone.now() - timedelta(days=10),
            grace_period_days=0,
        )
        self.company.refresh_from_db()
        expire_company(self.company)
        self.company.refresh_from_db()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.EXPIRED)
        self.assertTrue(_is_blocked(self.company)[0])

    def test_change_plan_syncs_billing_plan(self):
        plan = SubscriptionPlan.objects.filter(code='business').first()
        if plan is None:
            plan = SubscriptionPlan.objects.create(
                code='business', name='Business', is_active=True,
            )
        change_plan(self.company, plan=plan)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.plan, Subscription.Plan.PRO)
        self.assertTrue(SubscriptionEvent.objects.filter(
            subscription=self.sub, action=SubscriptionEvent.Action.PLAN_CHANGED,
        ).exists())

    def test_gate_ignores_stale_billing_record(self):
        # РЕГРЕССИЯ: устаревшая billing-запись (истёкшая) не должна блокировать
        # компанию, поля которой говорят, что подписка активна. Этот сценарий
        # возникал до синхронизации; теперь он защищает от рецидива.
        Company.objects.filter(pk=self.company.pk).update(
            subscription_end=timezone.now() + timedelta(days=30),
        )
        self.company.refresh_from_db()
        Subscription.objects.filter(pk=self.sub.pk).update(
            expires_at=timezone.now() - timedelta(days=30),
            status=Subscription.Status.ACTIVE,
        )
        self.assertFalse(_is_blocked(self.company)[0])
        self.assertTrue(self.company.is_subscription_active)

    def test_billing_mutation_still_syncs_to_company(self):
        # Обратное направление (billing → Company) не сломано: заморозка
        # через billing-сервис отражается на полях Company.
        self._expire_both()
        from .services import freeze_subscription as billing_freeze
        self.assertTrue(billing_freeze(self.sub))
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.FROZEN)
        self.assertTrue(_is_blocked(self.company)[0])

    def test_manual_billing_extend_after_companies_freeze(self):
        # Смешанный сценарий: companies заморозила, billing продлила —
        # обе модели сходятся к активному состоянию с одинаковым сроком.
        freeze_company(self.company)
        from .services import extend_subscription as billing_extend
        billing_extend(self.sub, days=30)
        self.company.refresh_from_db()
        self.sub.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.ACTIVE)
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(self.sub.expires_at, self.company.subscription_end)
        self.assertFalse(_is_blocked(self.company)[0])

    def test_material_ordering_works_after_renewal(self):
        # Полный цикл после продления: создание данных и чтение — без 403.
        self._expire_both()
        extend_subscription(self.company, days=30)
        token = self._login(self.owner)
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        resp = self.api.post('/api/v1/warehouse/raw-materials/', {
            'name': 'Гранит', 'quantity': '10', 'unit': 'm2',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(RawMaterial.objects.filter(company=self.company, name='Гранит').exists())
