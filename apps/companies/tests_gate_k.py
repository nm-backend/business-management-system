"""
Subscription gate: сквозные тесты блокировки бизнеса подпиской.

Единственный источник истины — Company.subscription_* (effective status
учитывает льготный период). Покрыто:
  - полный цикл active → grace → expired → extended → active;
  - гейт единообразно блокирует ВСЕ бизнес-эндпоинты для ВСЕХ ролей;
  - whitelist живёт в заморозке (вход, профиль, своя подписка, служебные);
  - данные переживают заморозку и продление; бизнес-операции возобновляются;
  - каскадное удаление компании не оставляет подписочных «сирот»;
  - удаление владельца не стирает историю (actor → NULL);
  - блокировка компании (toggle_active) и заморозка подписки независимы;
  - супер-админ гейтом не затрагивается; WS-чат закрыт в заморозке;
  - Beat-расписание жизненного цикла зарегистрировано.

Gate тестируется НАСТОЯЩИМИ токенами (login + Authorization): middleware
работает до DRF и не видит force_authenticate.
"""
from datetime import date, timedelta
from decimal import Decimal

from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import PushSubscription, User
from apps.audit.models import AuditLog
from apps.clients.models import Client
from apps.companies.models import Company, SubscriptionChange
from apps.companies.subscriptions import extend_subscription, freeze_company
from apps.companies.tasks import auto_freeze_expired_subscriptions
from apps.finance.models import Expense, ExpenseCategory, LaborRate
from apps.messaging.models import Notification, WsTicket
from apps.messaging.routing import websocket_urlpatterns
from apps.messaging.services import issue_ws_ticket
from apps.messaging.ws_auth import TicketAuthMiddleware
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct, RawMaterial

from .tests_subscriptions import make_admin, make_company, make_owner

# Представители всех бизнес-моделей: склад, заказы, клиенты, финансы,
# производство, сообщения, аудит, аккаунты.
BUSINESS_ENDPOINTS = [
    '/api/v1/warehouse/raw-materials/',
    '/api/v1/warehouse/finished-products/',
    '/api/v1/orders/orders/',
    '/api/v1/clients/clients/',
    '/api/v1/finance/expenses/',
    '/api/v1/finance/labor-rates/',
    '/api/v1/production/tasks/',
    '/api/v1/production/works/',
    '/api/v1/messaging/conversations/',
    '/api/v1/messaging/notifications/',
    '/api/v1/audit/logs/',
    '/api/v1/accounts/users/',
]


class GateLifecycleTests(TestCase):
    """Цикл подписки и блокировка бизнеса единым гейтом."""

    def setUp(self):
        self.company = make_company(name='GateCo')
        self.owner = make_owner(self.company, username='gate_owner')
        self.owner.set_password('pw')
        self.owner.save(update_fields=['password'])
        self.admin = make_admin(self.company, username='gate_admin')
        self.admin.set_password('pw')
        self.admin.save(update_fields=['password'])
        self.manager = User.objects.create_user(
            username='gate_mgr', password='pw',
            role=User.Role.MANAGER, company=self.company,
        )
        self.worker = User.objects.create_user(
            username='gate_w', password='pw',
            role=User.Role.WORKER, company=self.company,
        )
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.api = APIClient()

    def _login(self, user):
        resp = self.api.post('/api/v1/accounts/login/', {
            'username': user.username, 'password': 'pw', 'fingerprint': 'x' * 32,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data['tokens']['access']

    def _auth(self, user):
        # Сбрасываем force_authenticate: middleware читает Authorization,
        # а DRF-view — forced-user, рассинхрон давал бы 403 IsCompanyMember.
        self.api.force_authenticate(user=None)
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {self._login(user)}')

    def _expire(self, days=1):
        end = timezone.now() - timedelta(days=days)
        Company.objects.filter(pk=self.company.pk).update(subscription_end=end)

    def _expire_and_freeze(self):
        # Срок истёк и льготный период (7 дней) вышел — Celery переводит
        # компанию в EXPIRED (бизнес заблокирован).
        self._expire(8)
        processed = auto_freeze_expired_subscriptions()
        self.assertEqual(processed, 1)
        self.company.refresh_from_db()
        self.assertEqual(
            self.company.subscription_status, Company.SubscriptionStatus.EXPIRED,
        )

    def test_full_cycle_active_grace_expired_extended(self):
        # 1. Активная подписка — бизнес работает.
        self._auth(self.owner)
        self.assertEqual(self.api.get('/api/v1/warehouse/raw-materials/').status_code, 200)

        # 2. Срок истёк, но идёт льготный период — бизнес ПРОДОЛЖАЕТ работать.
        self._expire(1)
        resp = self.api.get('/api/v1/warehouse/raw-materials/')
        self.assertEqual(resp.status_code, 200, resp.data)

        # 3. Celery: active -> grace, льготный период начался.
        processed = auto_freeze_expired_subscriptions()
        self.assertEqual(processed, 1)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.GRACE)
        self.assertGreater(self.company.grace_end, timezone.now())

        # 4. Льготный период вышел -> expired, гейт закрыт (fail-closed).
        self._expire(8)
        processed = auto_freeze_expired_subscriptions()
        self.assertEqual(processed, 1)
        self.company.refresh_from_db()
        self.assertEqual(
            self.company.subscription_status, Company.SubscriptionStatus.EXPIRED,
        )
        self.assertFalse(self.company.is_subscription_active)
        resp = self.api.get('/api/v1/warehouse/raw-materials/')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['code'], 'subscription_expired')

        # 5. Вход работает; /me/ сообщает об истечении.
        self.assertEqual(self.api.get('/api/v1/accounts/me/').status_code, 200)
        me = self.api.get('/api/v1/accounts/me/').data
        self.assertTrue(me['subscription']['is_frozen'])

        # 6. Своя подписка доступна (whitelist gate).
        resp = self.api.get('/api/v1/companies/my-subscription/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['subscription_status'], 'expired')

        # 7. Супер-админ продлевает — компания возвращается в active.
        # Сбрасываем компонентный токен владельца: gate читает Authorization,
        # и протухший заголовок дал бы 403 раньше, чем view увидит суперадмина.
        self.api.credentials()
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.post(
            f'/api/v1/companies/{self.company.pk}/subscription_extend/',
            {'days': 30}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.company.refresh_from_db()
        self.assertEqual(
            self.company.subscription_status, Company.SubscriptionStatus.ACTIVE,
        )
        self.assertTrue(self.company.is_subscription_active)
        self.assertGreater(
            self.company.subscription_end, timezone.now() + timedelta(days=29),
        )

        # 8. Бизнес снова работает.
        self._auth(self.owner)
        self.assertEqual(self.api.get('/api/v1/warehouse/raw-materials/').status_code, 200)

    def test_gate_blocks_all_business_models_for_all_roles(self):
        """Заморозка: НИ ОДИН бизнес-эндпоинт не доступен ни одной роли."""
        self._expire_and_freeze()
        for user in (self.owner, self.admin, self.manager, self.worker):
            self._auth(user)
            for url in BUSINESS_ENDPOINTS:
                resp = self.api.get(url)
                self.assertEqual(
                    resp.status_code, 403,
                    f'{user.username} / {url}: {resp.status_code} (ожидался gate 403)',
                )
                self.assertEqual(
                    resp.json()['code'], 'subscription_expired',
                    f'{user.username} / {url}: неверный код гейта',
                )

    def test_whitelist_lives_while_frozen(self):
        """Вход, профиль, своя подписка и служебные работают в заморозке."""
        self._expire_and_freeze()
        self._auth(self.owner)
        self.assertEqual(self.api.get('/api/v1/accounts/me/').status_code, 200)
        self.assertEqual(
            self.api.get('/api/v1/companies/my-subscription/').status_code, 200,
        )
        # Запрос продления — тоже whitelist (иначе владелец не выберется).
        resp = self.api.post('/api/v1/companies/my-subscription/request-renewal/')
        self.assertIn(resp.status_code, (200, 201), resp.data)
        self.assertEqual(self.api.get('/api/v1/core/health/').status_code, 200)
        # Повторный вход замороженной компании работает (вход не блокируем).
        resp = self.api.post('/api/v1/accounts/login/', {
            'username': self.worker.username, 'password': 'pw', 'fingerprint': 'y' * 32,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_freeze_does_not_touch_company_block_and_user_active(self):
        """Заморозка ≠ блокировка компании: вход остаётся возможным."""
        self._expire()
        auto_freeze_expired_subscriptions()
        self.company.refresh_from_db()
        self.assertTrue(self.company.is_active)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)

    def test_celery_freeze_is_idempotent(self):
        self._expire(8)
        auto_freeze_expired_subscriptions()
        processed = auto_freeze_expired_subscriptions()
        self.assertEqual(processed, 0)
        self.company.refresh_from_db()
        self.assertEqual(
            self.company.subscription_status, Company.SubscriptionStatus.EXPIRED,
        )

    def test_worker_sees_frozen_me_but_not_owner_subscription(self):
        self._expire_and_freeze()
        self._auth(self.worker)
        me = self.api.get('/api/v1/accounts/me/').data
        self.assertTrue(me['subscription']['is_frozen'])
        # Своя подписка — только владелец/админ.
        self.assertEqual(
            self.api.get('/api/v1/companies/my-subscription/').status_code, 403,
        )

    def test_whitelist_allows_logout_when_frozen(self):
        self._expire()
        auto_freeze_expired_subscriptions()
        self._auth(self.owner)
        resp = self.api.post('/api/v1/accounts/logout/', {
            'refresh': 'invalid-refresh',
        }, format='json')
        # Whitelist пропускает, а view отвечает понятной ошибкой на мусорный refresh.
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.api.get('/api/v1/core/health/').status_code, 200)

    def test_superadmin_is_not_affected_by_subscription_gate(self):
        # Супер-админ не привязан к компании — gate его не трогает (а
        # бизнес-данные ему закрыты IsCompanyMember, это другой механизм).
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.get('/api/v1/warehouse/raw-materials/')
        self.assertEqual(resp.status_code, 403)
        self.assertNotEqual(resp.data.get('code'), 'subscription_expired')

    def test_frozen_company_cannot_issue_ws_ticket(self):
        """
        Выдача WS-тикета (чат) — бизнес-функция: замороженная компания
        получает subscription_expired, а не тикет.
        """
        self._auth(self.owner)
        # До заморозки тикет выдаётся.
        self.assertEqual(self.api.get('/api/v1/messaging/ws-ticket/').status_code, 200)

        # Заморозка → тикет больше не выдаётся (бизнес-функция).
        self._expire_and_freeze()
        resp = self.api.get('/api/v1/messaging/ws-ticket/')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['code'], 'subscription_expired')

        # А вот своя подписка — whitelist, работает.
        self.assertEqual(
            self.api.get('/api/v1/companies/my-subscription/').status_code, 200,
        )


class GateCrossModelTests(TestCase):
    """Данные переживают заморозку; каскады удаления; независимость блокировок."""

    def setUp(self):
        self.company = make_company(name='GateCrossCo')
        self.owner = make_owner(self.company, username='gc_owner', password='pw')
        self.superadmin = User.objects.create_superuser(username='root', password='pw')

        self.material = RawMaterial.objects.create(
            company=self.company, name='Мрамор', quantity=Decimal('100'),
        )
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('10'),
        )
        self.client = Client.objects.create(company=self.company, name='Клиент')
        self.order = Order.objects.create(
            company=self.company, client=self.client, product=self.product,
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('100'),
            deadline=date(2026, 12, 31),
        )
        LaborRate.objects.create(
            company=self.company, product=self.product,
            operation=LaborRate.OperationType.OTHER,
            rate_per_unit=Decimal('50'), unit='sht',
        )
        Expense.objects.create(
            company=self.company, category=ExpenseCategory.RENT,
            amount=Decimal('100'), date=date.today(),
        )
        self.api = APIClient()

    def _login(self, user):
        resp = self.api.post('/api/v1/accounts/login/', {
            'username': user.username, 'password': 'pw', 'fingerprint': 'x' * 32,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data['tokens']['access']

    def _auth(self, user):
        self.api.force_authenticate(user=None)
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {self._login(user)}')

    def test_business_data_survives_freeze_and_extend(self):
        """Остатки и суммы не меняются при заморозке и после продления."""
        end = timezone.now() - timedelta(days=8)
        Company.objects.filter(pk=self.company.pk).update(subscription_end=end)
        self.assertEqual(auto_freeze_expired_subscriptions(), 1)

        # Супер-админ продлевает компанию.
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.post(
            f'/api/v1/companies/{self.company.pk}/subscription_extend/',
            {'days': 30}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.company.refresh_from_db()
        self.assertEqual(
            self.company.subscription_status, Company.SubscriptionStatus.ACTIVE,
        )
        self.assertTrue(self.company.is_subscription_active)

        # Данные нетронуты.
        self.material.refresh_from_db()
        self.product.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('100'))
        self.assertEqual(self.product.quantity, Decimal('10'))
        self.assertEqual(self.order.total_amount, Decimal('100'))

        # Реальная бизнес-операция снова работает.
        self._auth(self.owner)
        resp = self.api.post('/api/v1/warehouse/raw-materials/', {
            'name': 'Гранит', 'quantity': '5',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(
            RawMaterial.objects.filter(company=self.company, name='Гранит').count(), 1,
        )

    def test_company_delete_cascades_subscription_rows(self):
        """Удаление компании не оставляет «сирот»: подписка, уведомления, аудит, WS, push."""
        extend_subscription(self.company, days=30, actor=self.owner)
        Notification.objects.create(
            company=self.company, user=self.owner,
            type=Notification.NotificationType.SUBSCRIPTION_EXPIRING,
            title='t', message='m',
        )
        WsTicket.objects.create(
            company=self.company, user=self.owner, ticket='ticket-x',
            expires_at=timezone.now() + timedelta(minutes=1),
        )
        PushSubscription.objects.create(
            company=self.company, user=self.owner,
            endpoint='https://push.example/x', p256dh_key='k', auth_key='a',
        )
        # История и аудит есть от продления выше.
        self.assertTrue(
            SubscriptionChange.objects.filter(company=self.company).exists(),
        )
        self.assertTrue(AuditLog.objects.filter(company=self.company).exists())

        company_pk = self.company.pk
        self.company.delete()

        self.assertFalse(
            SubscriptionChange.objects.filter(company_id=company_pk).exists(),
        )
        self.assertFalse(Notification.objects.filter(company_id=company_pk).exists())
        self.assertFalse(WsTicket.objects.filter(company_id=company_pk).exists())
        self.assertFalse(
            PushSubscription.objects.filter(company_id=company_pk).exists(),
        )
        self.assertFalse(AuditLog.objects.filter(company_id=company_pk).exists())
        # Бизнес-данные тоже каскадно удалены (изоляция не оставляет мусора).
        self.assertFalse(RawMaterial.objects.filter(company_id=company_pk).exists())
        self.assertFalse(Order.objects.filter(company_id=company_pk).exists())

    def test_owner_delete_keeps_change_history(self):
        """Удаление владельца не стирает историю: actor → NULL, запись жива."""
        extend_subscription(self.company, days=30, actor=self.owner)
        change = SubscriptionChange.objects.filter(
            company=self.company, action=SubscriptionChange.Action.EXTENDED,
        ).first()
        self.assertIsNotNone(change)
        self.assertEqual(change.actor, self.owner)

        self.owner.delete()
        change.refresh_from_db()
        self.assertIsNone(change.actor)
        # Компания живёт дальше.
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())

    def test_toggle_active_does_not_touch_subscription(self):
        # Замораживаем подписку: is_active компании не меняется (вход жив).
        freeze_company(self.company, actor=self.superadmin)
        self.company.refresh_from_db()
        self.assertEqual(
            self.company.subscription_status, Company.SubscriptionStatus.FROZEN,
        )
        self.assertTrue(self.company.is_active)
        self.assertTrue(self.owner.is_active)

        # Супер-админ блокирует компанию: вход гаснет, подписка не тронута.
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.post(f'/api/v1/companies/{self.company.pk}/toggle_active/')
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        self.owner.refresh_from_db()
        self.assertFalse(self.company.is_active)
        self.assertFalse(self.owner.is_active)
        self.company.refresh_from_db()
        self.assertEqual(
            self.company.subscription_status, Company.SubscriptionStatus.FROZEN,
        )

        # Разблокировка компании: пользователи снова активны, подписка как была.
        resp = self.api.post(f'/api/v1/companies/{self.company.pk}/toggle_active/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.company.refresh_from_db()
        self.owner.refresh_from_db()
        self.assertTrue(self.company.is_active)
        self.assertTrue(self.owner.is_active)
        self.company.refresh_from_db()
        self.assertEqual(
            self.company.subscription_status, Company.SubscriptionStatus.FROZEN,
        )
        self.assertFalse(self.company.is_subscription_active)


class GateWsTests(TransactionTestCase):
    """
    WebSocket-чат для замороженной компании не открывается даже по тикету,
    выданному до заморозки (тикет живёт до 60 секунд).
    """

    def setUp(self):
        self.company = make_company(name='GateWsCo')
        self.owner = make_owner(self.company, username='gw_owner')
        self.ws_app = TicketAuthMiddleware(URLRouter(websocket_urlpatterns))

    async def test_ws_rejected_for_frozen_company(self):
        ticket = await database_sync_to_async(issue_ws_ticket)(self.owner)
        # Заморозка после выдачи тикета.
        await database_sync_to_async(self._freeze)()
        communicator = WebsocketCommunicator(self.ws_app, f'/ws/chat/?ticket={ticket}')
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_ws_ok_for_active_company(self):
        ticket = await database_sync_to_async(issue_ws_ticket)(self.owner)
        communicator = WebsocketCommunicator(self.ws_app, f'/ws/chat/?ticket={ticket}')
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.disconnect()

    def _freeze(self):
        freeze_company(Company.objects.get(pk=self.company.pk))


class SubscriptionBeatScheduleTests(TestCase):
    """Расписание жизненного цикла ведётся контуром companies (grace-aware)."""

    def test_companies_lifecycle_tasks_scheduled(self):
        from django_celery_beat.models import PeriodicTask
        names = set(
            PeriodicTask.objects.filter(name__startswith='subscription-')
            .values_list('name', flat=True)
        )
        self.assertIn('subscription-auto-freeze', names)
        self.assertIn('subscription-expiry-notify', names)
        for name in ('subscription-auto-freeze', 'subscription-expiry-notify'):
            task = PeriodicTask.objects.get(name=name)
            self.assertTrue(task.enabled)
