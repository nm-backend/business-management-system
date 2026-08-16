"""
Полный lifecycle подписки: активная → истекла → заморожена → продлена → активная.

Покрыто:
  - провижининг 30 дней при создании компании (сигнал);
  - Celery-задача истечения (expired → frozen, идемпотентность);
  - единый subscription gate: бизнес заблокирован с code='subscription_expired',
    вход/профиль/статус подписки/оплата доступны (whitelist);
  - заморозка не трогает Company.is_active и is_active пользователей;
  - продление по счёту (owner → invoice pending → superadmin confirm → active);
  - автоматический возврат в работу после продления;
  - напоминания об окончании (раз в день, только в окне предупреждения);
  - расписание Celery Beat создано миграцией.

Gate тестируется НАСТОЯЩИМИ токенами (login + Authorization): middleware
работает до DRF и не видит force_authenticate.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.companies.models import Company
from apps.messaging.models import Notification

from .models import Invoice, Subscription, SubscriptionEvent
from .tasks import check_expired_subscriptions, notify_expiring_subscriptions


def make_company(name):
    company = Company.objects.create(name=name)
    owner = User.objects.create_user(
        username=f'{name}_owner', password='pw', role=User.Role.OWNER, company=company,
    )
    return company, owner


class SubscriptionProvisioningTests(TestCase):
    """Компания при создании получает подписку на 30 дней."""

    def test_company_creation_provisions_30_day_subscription(self):
        company, _owner = make_company('ProvCo')
        sub = Subscription.objects.get(company=company)
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertFalse(sub.is_blocked)
        self.assertAlmostEqual((sub.expires_at - timezone.now()).days, 30, delta=1)
        # Событие создания в истории.
        self.assertTrue(
            SubscriptionEvent.objects.filter(subscription=sub, action='created').exists(),
        )
        # Повторное сохранение компании не плодит подписки.
        company.save()
        self.assertEqual(Subscription.objects.filter(company=company).count(), 1)

    def test_days_left_and_is_blocked_helpers(self):
        company, _owner = make_company('HelperCo')
        sub = Subscription.objects.get(company=company)
        self.assertGreaterEqual(sub.days_left, 29)
        # Просроченная, но формально active (Celery ещё не прогнал) — заблокирована.
        Subscription.objects.filter(pk=sub.pk).update(
            expires_at=timezone.now() - timedelta(days=1),
        )
        sub.refresh_from_db()
        self.assertTrue(sub.is_blocked)
        self.assertEqual(sub.days_left, 0)


class SubscriptionLifecycleTests(TestCase):
    """active → expired → frozen → renewed → active (сквозной сценарий)."""

    def setUp(self):
        self.company, self.owner = make_company('LifeCo')
        self.worker = User.objects.create_user(
            username='life_w', password='pw', role=User.Role.WORKER, company=self.company,
        )
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.sub = Subscription.objects.get(company=self.company)
        self.api = APIClient()

    def _login(self, user):
        resp = self.api.post('/api/v1/accounts/login/', {
            'username': user.username, 'password': 'pw', 'fingerprint': 'x' * 32,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data['tokens']['access']

    def _auth(self, user):
        # Сбрасываем force_authenticate (если до этого был супер-админ):
        # middleware читает Authorization-заголовок, а DRF-view — forced-user,
        # рассинхрон давал 403 IsCompanyMember вместо ожидаемого запроса.
        self.api.force_authenticate(user=None)
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {self._login(user)}')

    def _expire(self, days=1):
        Subscription.objects.filter(pk=self.sub.pk).update(
            expires_at=timezone.now() - timedelta(days=days),
        )

    def test_full_cycle_active_expired_frozen_renewed(self):
        # 1. Активная подписка — бизнес работает.
        self._auth(self.owner)
        self.assertEqual(self.api.get('/api/v1/warehouse/raw-materials/').status_code, 200)

        # 2. Срок истёк, Celery ещё не прогнал — гейт уже закрыт (fail-closed).
        self._expire()
        resp = self.api.get('/api/v1/warehouse/raw-materials/')
        self.assertEqual(resp.status_code, 403)
        # Ответ приходит из middleware (JsonResponse), поэтому читаем через json().
        self.assertEqual(resp.json()['code'], 'subscription_expired')

        # 3. Celery: expired → frozen, события и аудит.
        result = check_expired_subscriptions()
        self.assertEqual(result['frozen'], 1)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)
        self.assertTrue(self.sub.is_blocked)
        self.assertIsNotNone(self.sub.frozen_at)
        actions = list(
            SubscriptionEvent.objects.filter(subscription=self.sub)
            .values_list('action', flat=True)
        )
        self.assertIn(SubscriptionEvent.Action.EXPIRED, actions)
        self.assertIn(SubscriptionEvent.Action.FROZEN, actions)
        self.assertTrue(AuditLog.objects.filter(
            action=AuditLog.Action.SUBSCRIPTION_FROZEN, object_id=str(self.sub.pk),
        ).exists())
        self.assertTrue(Notification.objects.filter(
            type=Notification.NotificationType.SUBSCRIPTION_FROZEN,
        ).exists())

        # 4. Вход работает; /me/ сообщает о заморозке.
        self.assertEqual(self.api.get('/api/v1/accounts/me/').status_code, 200)
        me = self.api.get('/api/v1/accounts/me/').data
        self.assertTrue(me['subscription']['is_frozen'])

        # 5. Статус подписки и продление доступны (whitelist gate).
        resp = self.api.get('/api/v1/billing/subscription/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['status'], 'frozen')
        self.assertEqual(resp.data['is_blocked'], True)

        # 6. Супер-админ продлевает — компания автоматически возвращается в active.
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub.pk}/extend/',
            {'days': 30}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertFalse(self.sub.is_blocked)
        self.assertIsNone(self.sub.frozen_at)
        self.assertGreater(self.sub.expires_at, timezone.now() + timedelta(days=29))

        # 7. Бизнес снова работает.
        self._auth(self.owner)
        self.assertEqual(self.api.get('/api/v1/warehouse/raw-materials/').status_code, 200)

    def test_freeze_does_not_touch_company_block_and_user_active(self):
        """Заморозка ≠ блокировка компании: вход остаётся возможным."""
        self._expire()
        check_expired_subscriptions()
        self.company.refresh_from_db()
        self.assertTrue(self.company.is_active)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)

    def test_celery_freeze_is_idempotent(self):
        self._expire()
        check_expired_subscriptions()
        result = check_expired_subscriptions()
        self.assertEqual(result['frozen'], 0)
        self.assertEqual(
            SubscriptionEvent.objects.filter(subscription=self.sub, action='frozen').count(),
            1,
        )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)

    def test_worker_sees_frozen_me_but_not_billing_management(self):
        self._expire()
        check_expired_subscriptions()
        self._auth(self.worker)
        me = self.api.get('/api/v1/accounts/me/').data
        self.assertTrue(me['subscription']['is_frozen'])
        # Управление подпиской — только владелец.
        self.assertEqual(self.api.get('/api/v1/billing/subscription/').status_code, 403)

    def test_whitelist_allows_logout_when_frozen(self):
        self._expire()
        check_expired_subscriptions()
        self._auth(self.owner)
        resp = self.api.post('/api/v1/accounts/logout/', {
            'refresh': 'invalid-refresh',
        }, format='json')
        # Whitelist пропускает, а view отвечает понятной ошибкой на мусорный refresh.
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.api.get('/api/v1/core/health/').status_code, 200)

    def test_owner_renew_creates_invoice_superadmin_confirm_renews(self):
        self._auth(self.owner)
        resp = self.api.post('/api/v1/billing/subscription/renew/', {
            'plan': 'pro',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        invoice_id = resp.data['id']
        invoice = Invoice.objects.get(pk=invoice_id)
        self.assertEqual(invoice.status, Invoice.Status.PENDING)
        self.assertEqual(invoice.metadata['plan'], 'pro')

        # Повторное продление возвращает тот же pending-счёт — без дубликатов.
        resp2 = self.api.post('/api/v1/billing/subscription/renew/', {
            'plan': 'pro',
        }, format='json')
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.data['id'], invoice_id)
        self.assertEqual(
            Invoice.objects.filter(subscription=self.sub, status='pending').count(), 1,
        )

        # До подтверждения подписка и тариф не меняются.
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.plan, Subscription.Plan.FREE)

        # Супер-админ подтверждает оплату → продление + смена тарифа.
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub.pk}/confirm_payment/',
            {'invoice_id': invoice_id}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertIsNotNone(invoice.paid_at)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(self.sub.plan, Subscription.Plan.PRO)
        self.assertGreater(self.sub.expires_at, timezone.now() + timedelta(days=29))
        self.assertTrue(Notification.objects.filter(
            type=Notification.NotificationType.SUBSCRIPTION_RENEWED,
        ).exists())

        # Идемпотентность confirm: повторный вызов не ломает.
        resp3 = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub.pk}/confirm_payment/',
            {'invoice_id': invoice_id}, format='json',
        )
        self.assertEqual(resp3.status_code, 200)

    def test_renew_after_freeze_restores_company(self):
        self._expire()
        check_expired_subscriptions()
        self._auth(self.owner)
        resp = self.api.post('/api/v1/billing/subscription/renew/', format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.api.force_authenticate(user=self.superadmin)
        self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub.pk}/confirm_payment/',
            {'invoice_id': resp.data['id']}, format='json',
        )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertFalse(self.sub.is_blocked)
        self._auth(self.owner)
        self.assertEqual(self.api.get('/api/v1/warehouse/raw-materials/').status_code, 200)

    def test_superadmin_activate_fresh_period(self):
        self._expire()
        check_expired_subscriptions()
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub.pk}/activate/',
            {'days': 30}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertFalse(self.sub.is_blocked)
        # Активность зафиксирована в аудите и истории.
        self.assertTrue(AuditLog.objects.filter(
            action=AuditLog.Action.SUBSCRIPTION_ACTIVATED, object_id=str(self.sub.pk),
        ).exists())

    def test_unfreeze_requires_future_expiry(self):
        self._expire()
        check_expired_subscriptions()
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub.pk}/unfreeze/', format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.data)


class SubscriptionReminderTests(TestCase):
    """Напоминания об окончании — только в окне, не чаще раза в день."""

    def setUp(self):
        self.company, self.owner = make_company('RemindCo')
        self.sub = Subscription.objects.get(company=self.company)

    def test_reminder_sent_within_threshold_once_per_day(self):
        Subscription.objects.filter(pk=self.sub.pk).update(
            expires_at=timezone.now() + timedelta(days=2),
        )
        result = notify_expiring_subscriptions()
        self.assertEqual(result['reminders'], 1)
        self.assertTrue(Notification.objects.filter(
            type=Notification.NotificationType.SUBSCRIPTION_EXPIRING,
            user=self.owner,
        ).exists())
        self.sub.refresh_from_db()
        self.assertIsNotNone(self.sub.last_reminder_at)
        # Повторный запуск в тот же день — без дубликатов.
        result2 = notify_expiring_subscriptions()
        self.assertEqual(result2['reminders'], 0)
        self.assertEqual(Notification.objects.filter(
            type=Notification.NotificationType.SUBSCRIPTION_EXPIRING,
        ).count(), 1)

    def test_no_reminder_outside_threshold(self):
        # 30 дней до окончания > окно предупреждения (3 дня).
        self.assertEqual(notify_expiring_subscriptions()['reminders'], 0)

    def test_no_reminder_after_expiry(self):
        Subscription.objects.filter(pk=self.sub.pk).update(
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertEqual(notify_expiring_subscriptions()['reminders'], 0)


class SubscriptionBeatScheduleTests(TestCase):
    """Расписание Celery Beat создаётся миграцией."""

    def test_periodic_tasks_exist(self):
        from django_celery_beat.models import PeriodicTask
        names = set(
            PeriodicTask.objects.filter(name__startswith='billing-')
            .values_list('name', flat=True)
        )
        self.assertIn('billing-check-expired', names)
        self.assertIn('billing-notify-expiring', names)
        task = PeriodicTask.objects.get(name='billing-check-expired')
        self.assertTrue(task.enabled)
        self.assertEqual(task.task, 'apps.billing.tasks.check_expired_subscriptions')
