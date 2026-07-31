"""
Интеграционные тесты роли manager (ЭТАП «полноценный менеджер»).

Менеджер получает ПРОСМОТР клиентов, заказов и производства (плюс склад без цен):
- GET  /clients/clients/           -> 200 (только чтение, без сумм)
- GET  /orders/orders/             -> 200 (видит ВСЕ заказы компании)
- GET  /production/tasks/          -> 200
- GET  /production/works/          -> 200 (без labor_cost — limited serializer)
- GET  /warehouse/raw-materials/   -> 200 (без purchase_price/avg_cost_price)
- GET  /reports/analytics/admin/   -> 200 (операционная аналитика без денег)

Запрещено (финансы/настройки/запись):
- GET  /finance/expenses/          -> 403
- GET  /reports/analytics/owner/   -> 403
- GET  /audit/                     -> 403
- GET  /accounts/users/            -> 200, но ПУСТОЙ список (настройки закрыты)
- POST /clients/clients/           -> 403 (менеджер не создаёт)
- POST /orders/orders/             -> 403
- POST /production/tasks/          -> 403
- POST /production/works/          -> 403
- PATCH/POST управление -> 403
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company

PASSWORD = 'Str0ng!Pass9'


class ManagerRoleRbacTests(TestCase):
    """Полный срез прав менеджера: просмотр операционных данных, запрет финансов/настроек."""

    def setUp(self):
        self.company = Company.objects.create(name='ManagerCo')
        self.owner = User.objects.create_user(
            username='mco_owner', password=PASSWORD, role=User.Role.OWNER, company=self.company,
        )
        self.manager = User.objects.create_user(
            username='mco_manager', password=PASSWORD, role=User.Role.MANAGER, company=self.company,
        )
        self.worker = User.objects.create_user(
            username='mco_worker', password=PASSWORD, role=User.Role.WORKER, company=self.company,
        )

        from apps.clients.models import Client
        from apps.warehouse.models import FinishedProduct, RawMaterial
        from apps.orders.models import Order
        from apps.production.models import Task

        self.client_obj = Client.objects.create(company=self.company, name='ClientM')
        self.material = RawMaterial.objects.create(
            company=self.company, name='MatM', quantity=Decimal('10'), unit='kg',
        )
        self.product = FinishedProduct.objects.create(
            company=self.company, name='ProdM', quantity=Decimal('5'), unit='sht',
        )
        self.order = Order.objects.create(
            company=self.company, client=self.client_obj, product=self.product,
            quantity=Decimal('1'), unit='izdelie',
        )
        self.task = Task.objects.create(
            company=self.company, order=self.order, worker=self.worker, assigned_by=self.owner,
        )

        from apps.warehouse.models import StockMovement
        StockMovement.objects.create(
            company=self.company, material=self.material, movement_type='incoming',
            quantity=Decimal('10'), price_per_unit=Decimal('5000'),
        )

        self.api = APIClient()
        self.api.force_authenticate(user=self.manager)

    def test_is_manager_flag_in_profile(self):
        resp = self.api.get('/api/v1/accounts/me/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['is_manager'])
        self.assertFalse(resp.data['is_owner'])
        self.assertFalse(resp.data['is_admin'])
        self.assertFalse(resp.data['is_worker'])

    def test_manager_can_view_clients(self):
        resp = self.api.get('/api/v1/clients/clients/')
        self.assertEqual(resp.status_code, 200)
        names = [c['name'] for c in resp.data['results']]
        self.assertIn('ClientM', names)
        # Без финансовых сумм: debt/total_paid доступны только владельцу.
        first = resp.data['results'][0]
        self.assertNotIn('debt', first)
        self.assertNotIn('total_paid', first)

    def test_manager_can_view_all_orders(self):
        resp = self.api.get('/api/v1/orders/orders/')
        self.assertEqual(resp.status_code, 200)
        ids = [o['id'] for o in resp.data['results']]
        self.assertIn(self.order.id, ids)
        # Суммы заказа — только владелец.
        first = resp.data['results'][0]
        self.assertNotIn('total_amount', first)
        self.assertNotIn('paid_amount', first)

    def test_manager_can_view_production(self):
        resp = self.api.get('/api/v1/production/tasks/')
        self.assertEqual(resp.status_code, 200)
        ids = [t['id'] for t in resp.data['results']]
        self.assertIn(self.task.id, ids)

        works = self.api.get('/api/v1/production/works/')
        self.assertEqual(works.status_code, 200)

    def test_manager_can_view_warehouse_without_prices(self):
        resp = self.api.get('/api/v1/warehouse/raw-materials/')
        self.assertEqual(resp.status_code, 200)
        first = resp.data['results'][0]
        self.assertNotIn('purchase_price', first)
        self.assertNotIn('avg_cost_price', first)

    def test_manager_can_view_stock_movements_without_prices(self):
        # Вкладка «Омбор ҳаракати»: manager видит историю, но без price_per_unit
        # (financial-поле скрыто limited-сериализатором). Работник её не видит.
        resp = self.api.get('/api/v1/warehouse/stock-movements/')
        self.assertEqual(resp.status_code, 200)
        for row in resp.data['results']:
            self.assertNotIn('price_per_unit', row)

        worker_api = APIClient()
        worker_api.force_authenticate(user=self.worker)
        self.assertEqual(worker_api.get('/api/v1/warehouse/stock-movements/').status_code, 403)

    def test_manager_can_view_operational_analytics(self):
        resp = self.api.get('/api/v1/reports/analytics/admin/')
        self.assertEqual(resp.status_code, 200)

    def test_manager_cannot_view_finance(self):
        self.assertEqual(self.api.get('/api/v1/finance/expenses/').status_code, 403)
        self.assertEqual(self.api.get('/api/v1/reports/analytics/owner/').status_code, 403)
        self.assertEqual(self.api.get('/api/v1/audit/logs/').status_code, 403)

    def test_manager_cannot_manage_accounts(self):
        resp = self.api.get('/api/v1/accounts/users/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['results']), 0)  # настройки/аккаунты скрыты

    def test_manager_cannot_write_clients(self):
        resp = self.api.post('/api/v1/clients/clients/', {'name': 'Hack'}, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(
            self.api.patch(f'/api/v1/clients/clients/{self.client_obj.id}/', {'name': 'X'}, format='json').status_code,
            403,
        )

    def test_manager_cannot_write_orders(self):
        resp = self.api.post('/api/v1/orders/orders/', {'comment': 'x'}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_manager_cannot_transition_orders(self):
        # Kanban двигает заказы через PATCH /transition/ — для manager это запись.
        resp = self.api.patch(
            f'/api/v1/orders/orders/{self.order.id}/transition/',
            {'status': 'sent_to_worker'},
            format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_manager_cannot_create_tasks_or_works(self):
        resp = self.api.post('/api/v1/production/tasks/', {'worker': self.worker.id}, format='json')
        self.assertEqual(resp.status_code, 403)
        resp = self.api.post(
            '/api/v1/production/works/',
            {'product': self.product.id, 'quantity': '1', 'unit': 'sht'},
            format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_manager_cannot_write_warehouse(self):
        resp = self.api.post(
            '/api/v1/warehouse/raw-materials/', {'name': 'Hack', 'quantity': '1'}, format='json',
        )
        self.assertEqual(resp.status_code, 403)
