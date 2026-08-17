"""
Кроссмодельная интеграция подписок со всем ERP-стеком.

Подписка — горизонтальный механизм поверх всех доменных моделей. Здесь
проверяется, что:

  - subscription gate единообразно блокирует ВСЕ бизнес-модели (склад,
    заказы, клиенты, финансы, производство, сообщения, аудит, аккаунты)
    для ВСЕХ ролей, а whitelist (вход, профиль, billing, служебные) живёт;
  - существующие данные (остатки, суммы заказов, расходы) переживают
    заморозку и продление без изменений;
  - после продления бизнес-операции снова работают (реальный POST);
  - удаление компании каскадно убирает все billing-строки без «сирот»
    (события, счета, уведомления, WS-тикеты, push, аудит);
  - удаление владельца не ломает историю подписки (actor → NULL);
  - блокировка компании супер-админом (toggle_active) и заморозка
    подписки — независимые механизмы и не конфликтуют.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import PushSubscription, User
from apps.audit.models import AuditLog
from apps.clients.models import Client
from apps.companies.models import Company
from apps.finance.models import Expense, ExpenseCategory, LaborRate
from apps.messaging.models import Notification, WsTicket
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct, RawMaterial

from .models import Invoice, Subscription, SubscriptionEvent
from .services import create_invoice, freeze_subscription, renew_subscription
from .tasks import check_expired_subscriptions

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


class SubscriptionCrossModelTests(TestCase):
    """Гейт блокирует весь стек; данные переживают заморозку и продление."""

    def setUp(self):
        self.company = Company.objects.create(name='CrossCo')
        self.owner = User.objects.create_user(
            username='cr_o', password='pw', role=User.Role.OWNER, company=self.company,
        )
        self.admin = User.objects.create_user(
            username='cr_a', password='pw', role=User.Role.ADMIN, company=self.company,
        )
        self.manager = User.objects.create_user(
            username='cr_m', password='pw', role=User.Role.MANAGER, company=self.company,
        )
        self.worker = User.objects.create_user(
            username='cr_w', password='pw', role=User.Role.WORKER, company=self.company,
        )
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.sub = Subscription.objects.get(company=self.company)

        # Бизнес-данные всех доменов.
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
        self.expense = Expense.objects.create(
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

    def _expire_and_freeze(self):
        Subscription.objects.filter(pk=self.sub.pk).update(
            expires_at=timezone.now() - timedelta(days=1),
        )
        result = check_expired_subscriptions()
        self.assertEqual(result['frozen'], 1)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)

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
        """Вход, профиль, статус подписки и служебные работают в заморозке."""
        self._expire_and_freeze()
        self._auth(self.owner)
        self.assertEqual(self.api.get('/api/v1/accounts/me/').status_code, 200)
        self.assertEqual(self.api.get('/api/v1/billing/subscription/').status_code, 200)
        self.assertEqual(self.api.get('/api/v1/core/health/').status_code, 200)
        # Повторный вход замороженной компании работает (не блокируем вход).
        resp = self.api.post('/api/v1/accounts/login/', {
            'username': self.worker.username, 'password': 'pw', 'fingerprint': 'y' * 32,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_business_data_survives_freeze_and_renew(self):
        """Остатки и суммы не меняются при заморозке и после продления."""
        self._expire_and_freeze()
        self.sub.refresh_from_db()

        # Супер-админ продлевает компанию.
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub.pk}/extend/',
            {'days': 30}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertFalse(self.sub.is_blocked)

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

    def test_company_delete_cascades_all_billing_rows(self):
        """Удаление компании не оставляет «сирот»: billing, уведомления, аудит, WS, push."""
        invoice, _ = create_invoice(self.sub, actor=self.owner)
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
        # Аудит есть от провижининга и продления (счёт создавался выше).
        self.assertTrue(AuditLog.objects.filter(company=self.company).exists())

        company_pk = self.company.pk
        self.company.delete()

        self.assertFalse(Subscription.objects.filter(company_id=company_pk).exists())
        self.assertFalse(SubscriptionEvent.objects.filter(company_id=company_pk).exists())
        self.assertFalse(Invoice.objects.filter(company_id=company_pk).exists())
        self.assertFalse(Notification.objects.filter(company_id=company_pk).exists())
        self.assertFalse(WsTicket.objects.filter(company_id=company_pk).exists())
        self.assertFalse(PushSubscription.objects.filter(company_id=company_pk).exists())
        self.assertFalse(AuditLog.objects.filter(company_id=company_pk).exists())
        # Бизнес-данные тоже каскадно удалены (изоляция не оставляет мусора).
        self.assertFalse(RawMaterial.objects.filter(company_id=company_pk).exists())
        self.assertFalse(Order.objects.filter(company_id=company_pk).exists())
        # Счёт удалился вместе с подпиской/компанией.
        self.assertFalse(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_owner_delete_keeps_subscription_event_history(self):
        """Удаление владельца не стирает историю: actor → NULL, роль сохранена."""
        # Событие с исполнителем (продление от владельца), затем удаляем его.
        renew_subscription(self.sub, actor=self.owner)
        event = SubscriptionEvent.objects.filter(
            company=self.company, action=SubscriptionEvent.Action.RENEWED,
        ).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.actor, self.owner)

        self.owner.delete()
        event.refresh_from_db()
        self.assertIsNone(event.actor)
        self.assertEqual(event.actor_role, 'owner')
        # Подписка и компания живут дальше.
        self.assertTrue(Subscription.objects.filter(company=self.company).exists())


class SubscriptionCompanyBlockInterplayTests(TestCase):
    """Блокировка компании (superadmin) и заморозка подписки — независимы."""

    def setUp(self):
        self.company = Company.objects.create(name='BlockCo')
        self.owner = User.objects.create_user(
            username='bl_o', password='pw', role=User.Role.OWNER, company=self.company,
        )
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.sub = Subscription.objects.get(company=self.company)
        self.api = APIClient()

    def test_toggle_active_does_not_touch_subscription(self):
        # Замораживаем подписку: is_active компании не меняется (вход жив).
        Subscription.objects.filter(pk=self.sub.pk).update(
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.sub.refresh_from_db()
        self.assertTrue(freeze_subscription(self.sub))
        self.company.refresh_from_db()
        self.assertTrue(self.company.is_active)
        self.assertTrue(self.owner.is_active)

        # Супер-админ блокирует компанию: вход гасится, подписка не тронута.
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.post(f'/api/v1/companies/{self.company.pk}/toggle_active/')
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        self.owner.refresh_from_db()
        self.assertFalse(self.company.is_active)
        self.assertFalse(self.owner.is_active)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)

        # Разблокировка компании: пользователи снова активны, подписка как была.
        resp = self.api.post(f'/api/v1/companies/{self.company.pk}/toggle_active/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.company.refresh_from_db()
        self.owner.refresh_from_db()
        self.assertTrue(self.company.is_active)
        self.assertTrue(self.owner.is_active)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)
        self.assertTrue(self.sub.is_blocked)
