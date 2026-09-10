"""
Консолидированная матрица доступа «роль → окно/действие» (серверная сторона).

Один прогон сверяет HTTP-код КАЖДОГО бизнес-окна с ожиданиями ТЗ для всех ролей:
  * owner (Egasi)        — всё;
  * admin (Administrator)— всё, кроме финансов (403 либо сериализатор без сумм);
  * manager              — только чтение клиентов/заказов/производства/склада;
  * worker (Ishchi)      — только своё: свои задачи/работы/заказы, склад на
                           чтение, чужие окна закрыты;
  * superadmin           — только платформенный контур, бизнес-данные 403.

Дополняет точечные тесты (tests_financial_isolation_v2, tests_manager_role_k):
матрица ловит регрессию на любом пересечении «эндпоинт × роль» — например,
если при рефакторинге у view пропадёт IsOwner или слетит ветка get_permissions.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.clients.models import Client
from apps.finance.models import LaborRate
from apps.orders.models import Order
from apps.production.models import Task, TaskStatus, WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial

ALL = {'owner': 200, 'admin': 200, 'manager': 200, 'worker': 200, 'superadmin': 403}
STAFF_READ = {'owner': 200, 'admin': 200, 'manager': 200, 'worker': 403, 'superadmin': 403}
OWNER_ONLY = {'owner': 200, 'admin': 403, 'manager': 403, 'worker': 403, 'superadmin': 403}
NO_SUPER = lambda o=200, a=200, m=200, w=200, s=403: {  # noqa: E731
    'owner': o, 'admin': a, 'manager': m, 'worker': w, 'superadmin': s,
}


class RoleAccessMatrixTests(TestCase):
    """HTTP-матрица «роль × эндпоинт» для всех окон из ТЗ."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='MatrixCo')
        cls.owner = User.objects.create_user(
            username='mx_owner', password='pw', role=User.Role.OWNER, company=cls.company)
        cls.admin = User.objects.create_user(
            username='mx_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
            can_create_workers=True)
        cls.manager = User.objects.create_user(
            username='mx_manager', password='pw', role=User.Role.MANAGER, company=cls.company)
        cls.worker = User.objects.create_user(
            username='mx_worker', password='pw', role=User.Role.WORKER, company=cls.company)
        cls.superadmin = User.objects.create_user(
            username='mx_super', password='pw', role=User.Role.SUPERADMIN, company=None)

        cls.material = RawMaterial.objects.create(
            company=cls.company, name='Мрамор', quantity=Decimal('100'),
            purchase_price=Decimal('5000'), avg_cost_price=Decimal('3500'), unit='m2')
        cls.product = FinishedProduct.objects.create(
            company=cls.company, name='Столешница', quantity=Decimal('10'),
            cost_price=Decimal('12000'), sale_price=Decimal('25000'), unit='izdelie')
        cls.customer = Client.objects.create(company=cls.company, name='МатрикоКлиент')
        cls.order = Order.objects.create(
            company=cls.company, client=cls.customer, product=cls.product,
            worker=cls.worker, quantity=Decimal('2'), unit='izdelie',
            status=Order.Status.IN_PROGRESS, total_amount=Decimal('50000'))
        cls.task = Task.objects.create(
            company=cls.company, order=cls.order, worker=cls.worker,
            assigned_by=cls.owner, status=TaskStatus.PENDING, title='Матрица')
        # Сданная на подтверждение работа — для confirm-действия works.
        cls.work = WorkRecord.objects.create(
            company=cls.company, task=cls.task, worker=cls.worker,
            product=cls.product, operation=LaborRate.OperationType.CUTTING,
            quantity=Decimal('1'), defect_quantity=Decimal('0'), unit='izdelie',
            labor_cost=Decimal('8000'),
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION)

    @classmethod
    def _fill(cls, url):
        return (url
                .replace('{order}', str(cls.order.pk))
                .replace('{task}', str(cls.task.pk))
                .replace('{work}', str(cls.work.pk))
                .replace('{worker}', str(cls.worker.pk))
                .replace('{client}', str(cls.customer.pk))
                .replace('{product}', str(cls.product.pk)))

    def _api(self, role):
        api = APIClient()
        api.force_authenticate(user=getattr(self, role if role != 'superadmin' else 'superadmin'))
        return api

    # ── READ-матрица: окно (GET-список) × роль ──────────────────────────
    READ_MATRIX = [
        # Окно «Заказы»: все видят, работник — только свои (проверяется ниже).
        ('/api/v1/orders/orders/', ALL),
        # Окно «Продажи» — только владелец (деньги).
        ('/api/v1/reports/analytics/sales/?period=month', OWNER_ONLY),
        # Склад сырья/готовой продукции — чтение для всех сотрудников (без цен не-owner).
        ('/api/v1/warehouse/raw-materials/', ALL),
        ('/api/v1/warehouse/finished-products/', ALL),
        ('/api/v1/warehouse/warehouses/', ALL),
        ('/api/v1/warehouse/cells/', ALL),
        # Приходные документы и рецепты — владелец/админ.
        ('/api/v1/warehouse/goods-receipts/', NO_SUPER(a=200, m=403, w=403)),
        ('/api/v1/warehouse/recipes/', NO_SUPER(a=200, m=403, w=403)),
        # История склада — владелец/админ/менеджер; работник не видит.
        ('/api/v1/warehouse/stock-movements/', NO_SUPER(a=200, m=200, w=403)),
        # Производство: задачи и работы — все сотрудники; worker видит только свои.
        ('/api/v1/production/tasks/', ALL),
        ('/api/v1/production/works/', ALL),
        # Мой заработок — сам работник (и владелец); админ/менеджер — нет.
        ('/api/v1/production/works/my_earnings/', NO_SUPER(o=200, a=403, m=403, w=200)),
        # Клиенты — владелец/админ/менеджер; работник не видит.
        ('/api/v1/clients/clients/', STAFF_READ),
        # Долги и оплаты — деньги, только владелец.
        ('/api/v1/clients/clients/debt_summary/', OWNER_ONLY),
        ('/api/v1/clients/payments/', OWNER_ONLY),
        # Финансы — только владелец.
        ('/api/v1/finance/expenses/', OWNER_ONLY),
        ('/api/v1/finance/worker-payments/', OWNER_ONLY),
        # Ставки труда: читают владелец/админ/работник (выбор операции), менеджер — нет.
        ('/api/v1/finance/labor-rates/', NO_SUPER(o=200, a=200, m=403, w=200)),
        # Аналитика владельца — только владелец.
        ('/api/v1/reports/analytics/owner/?period=month', OWNER_ONLY),
        ('/api/v1/reports/analytics/revenue-timeline/', OWNER_ONLY),
        # Операционная аналитика админа (без денег) и квартальный отчёт — без работника.
        ('/api/v1/reports/analytics/admin/', STAFF_READ),
        ('/api/v1/reports/analytics/quarterly/', STAFF_READ),
        # Экспорты: финансовый и выгрузка компании — владелец.
        ('/api/v1/reports/export/finance/?format=xlsx', OWNER_ONLY),
        ('/api/v1/reports/export/company-data/?format=xlsx', OWNER_ONLY),
        # Экспорты админа (без денежных колонок) — владелец/админ.
        ('/api/v1/reports/export/stock/?format=xlsx', NO_SUPER(a=200, m=403, w=403)),
        ('/api/v1/reports/export/orders/?format=xlsx', NO_SUPER(a=200, m=403, w=403)),
        ('/api/v1/reports/export/work/?format=xlsx', NO_SUPER(a=200, m=403, w=403)),
        # Аудит — только владелец.
        ('/api/v1/audit/logs/', OWNER_ONLY),
        # Сотрудники: владелец видит всех, админ — работников, manager/worker — пусто.
        # (Супер-админу список тоже открыт, но queryset пуст: компании у него нет.)
        ('/api/v1/accounts/users/', NO_SUPER(o=200, a=200, m=200, w=200, s=200)),
        # Чат: сотрудники/диалоги — все сотрудники компании.
        ('/api/v1/messaging/conversations/', ALL),
        ('/api/v1/messaging/employees/', ALL),
        # Платформенный контур: список компаний и бэкапы — только супер-админ;
        # своя подписка — владелец/админ (как и экран #/subscription).
        ('/api/v1/companies/',
         {'owner': 403, 'admin': 403, 'manager': 403, 'worker': 403, 'superadmin': 200}),
        ('/api/v1/companies/my-subscription/',
         {'owner': 200, 'admin': 200, 'manager': 403, 'worker': 403, 'superadmin': 403}),
        ('/api/v1/backup/logs/',
         {'owner': 403, 'admin': 403, 'manager': 403, 'worker': 403, 'superadmin': 200}),
    ]

    def test_read_matrix(self):
        problems = []
        for url, expected in self.READ_MATRIX:
            for role, want in expected.items():
                response = self._api(role).get(self._fill(url))
                if response.status_code != want:
                    problems.append(f'GET {url} как {role}: {response.status_code}, ожидалось {want}')
        self.assertFalse(problems, 'Матрица чтения разошлась:\n  ' + '\n  '.join(problems))

    # ── WRITE-матрица: действие × роль ──────────────────────────────────
    def test_write_matrix(self):
        today = timezone.localdate().isoformat()
        # '<403' — доступ разрешён (точный код зависит от состояния данных:
        # 201 создано, 400 бизнес-валидация), главное — НЕ отказ по роли.
        cases = [
            ('создать заказ', 'post', '/api/v1/orders/orders/',
             {'client': '{client}', 'product': None, 'quantity': '2', 'unit': 'izdelie',
              'custom_product_name': 'Матрица'},
             {'owner': 201, 'admin': 201, 'manager': 403, 'worker': 403, 'superadmin': 403}),
            ('изменить заказ', 'patch', '/api/v1/orders/orders/{order}/',
             {'comment': 'матрица'},
             {'owner': 200, 'admin': 200, 'manager': 403, 'worker': 403}),
            ('создать задачу (назначить)', 'post', '/api/v1/production/tasks/',
             {'title': 'Матрица', 'worker': '{worker}'},
             {'owner': 201, 'admin': 201, 'manager': 403, 'worker': 201, 'superadmin': 403}),
            # Работник с чужим worker= всё равно получает СВОЮ самостоятельную
            # задачу (сервер форсирует worker=request.user) — проверяется ниже
            # в test_worker_cannot_create_task_for_other_worker.
            ('создать свою задачу (worker)', 'post', '/api/v1/production/tasks/',
             {'title': 'Своя', 'worker': '{worker}'},
             {'manager': 403, 'worker': 201, 'superadmin': 403}),
            ('принять задачу', 'post', '/api/v1/production/tasks/{task}/accept/', {},
             {'owner': 403, 'admin': 403, 'manager': 403, 'worker': 200}),
            # confirm — действие РАБОТ (works), не задач: роль проверяется до данных.
            ('подтвердить работу', 'post', '/api/v1/production/works/{work}/confirm/', {},
             {'owner': '<403', 'admin': '<403', 'manager': 403, 'worker': 403}),
            ('отменить задачу', 'post', '/api/v1/production/tasks/{task}/cancel/', {},
             {'owner': '<403', 'admin': '<403', 'manager': 403, 'worker': 403}),
            ('создать клиента', 'post', '/api/v1/clients/clients/',
             {'name': 'МатрикоКлиент2'},
             {'owner': 201, 'admin': 201, 'manager': 403, 'worker': 403, 'superadmin': 403}),
            ('изменить клиента', 'patch', '/api/v1/clients/clients/{client}/',
             {'name': 'МатрикоКлиент3'},
             {'owner': 200, 'admin': 200, 'manager': 403, 'worker': 403}),
            ('принять оплату', 'post', '/api/v1/clients/payments/',
             {'client': '{client}', 'amount': '100', 'payment_date': '__now__'},
             {'owner': 201, 'admin': 403, 'manager': 403, 'worker': 403, 'superadmin': 403}),
            ('создать расход', 'post', '/api/v1/finance/expenses/',
             {'category': 'rent', 'amount': '5000', 'date': today},
             {'owner': 201, 'admin': 403, 'manager': 403, 'worker': 403, 'superadmin': 403}),
            ('создать ставку труда', 'post', '/api/v1/finance/labor-rates/',
             {'product': '{product}', 'operation': 'cutting', 'rate_per_unit': '100', 'unit': 'izdelie'},
             {'owner': 201, 'admin': 403, 'manager': 403, 'worker': 403}),
            # Логин уникален: подставляем роль, чтобы owner и admin не столкнулись.
            ('создать сотрудника (owner)', 'post', '/api/v1/accounts/users/',
             {'username': 'mx_new_{role}', 'role': 'worker', 'password': 'longpassword1'},
             {'owner': 201, 'admin': 201, 'manager': 403, 'worker': 403}),
            ('изменить сотрудника', 'patch', '/api/v1/accounts/users/{worker}/',
             {'full_name': 'Матрица'},
             {'owner': 200, 'admin': 403, 'manager': 403, 'worker': 403}),
            ('приход материала', 'post', '/api/v1/warehouse/raw-materials/',
             {'name': 'Матрица-сырьё', 'unit': 'm2', 'quantity': '5'},
             {'owner': 201, 'admin': 201, 'manager': 403, 'worker': 403}),
        ]
        problems = []
        for title, method, url, payload, expected in cases:
            for role, want in expected.items():
                data = {
                    key: (self._fill(value) if isinstance(value, str) else value)
                    for key, value in payload.items() if value is not None
                }
                if data.get('payment_date') == '__now__':
                    data['payment_date'] = timezone.now().isoformat()
                data = {
                    key: (value.replace('{role}', role) if isinstance(value, str) else value)
                    for key, value in data.items()
                }
                api = self._api(role)
                if method == 'post':
                    response = api.post(self._fill(url), data, format='json')
                else:
                    response = api.patch(self._fill(url), data, format='json')
                if want == '<403':
                    if response.status_code == 403:
                        problems.append(f'{title} как {role}: 403, ожидался допуск')
                elif response.status_code != want:
                    problems.append(
                        f'{title} как {role}: {response.status_code} {getattr(response, "data", "")}, '
                        f'ожидалось {want}')
        self.assertFalse(problems, 'Матрица записи разошлась:\n  ' + '\n  '.join(problems))

    # ── Изоляция «только своё» внутри открытых окон ─────────────────────
    def test_worker_sees_only_his_orders(self):
        """Работник в окне заказов видит только назначенные ему — и без сумм."""
        other = Client.objects.create(company=self.company, name='ЧужойЗаказКлиент')
        Order.objects.create(
            company=self.company, client=other, product=self.product,
            quantity=Decimal('1'), unit='izdelie', total_amount=Decimal('999'))
        response = self._api('worker').get('/api/v1/orders/orders/')
        self.assertEqual(response.status_code, 200)
        rows = response.data['results']
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row['worker'], self.worker.pk)
            # Деньги заказов работнику не отдаются (сериализатор без сумм).
            self.assertNotIn('total_amount', row)
            self.assertNotIn('paid_amount', row)

    def test_worker_sees_only_his_tasks(self):
        other_worker = User.objects.create_user(
            username='mx_worker2', password='pw', role=User.Role.WORKER, company=self.company)
        Task.objects.create(
            company=self.company, worker=other_worker, assigned_by=self.owner,
            status=TaskStatus.PENDING, title='Чужая задача')
        response = self._api('worker').get('/api/v1/production/tasks/')
        self.assertEqual(response.status_code, 200)
        rows = response.data['results']
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row['worker'], self.worker.pk)

    def test_worker_cannot_create_task_for_other_worker(self):
        """worker= чужой работник игнорируется: задача всё равно своя."""
        other_worker = User.objects.create_user(
            username='mx_worker3', password='pw', role=User.Role.WORKER, company=self.company)
        response = self._api('worker').post(
            '/api/v1/production/tasks/',
            {'title': 'Попытка на чужого', 'worker': other_worker.pk}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['worker'], self.worker.pk)
        self.assertTrue(response.data['is_self_assigned'])

    def test_admin_user_list_contains_only_workers(self):
        """Админ в «Сотрудниках» видит только работников, worker — пустоту."""
        response = self._api('admin').get('/api/v1/accounts/users/')
        self.assertEqual(response.status_code, 200)
        roles = {row['role'] for row in response.data['results']}
        self.assertEqual(roles, {'worker'})

        response = self._api('worker').get('/api/v1/accounts/users/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'], [])

    def test_admin_without_flag_cannot_create_workers(self):
        """can_create_workers=False — админ не создаёт сотрудников (403)."""
        limited = User.objects.create_user(
            username='mx_admin2', password='pw', role=User.Role.ADMIN, company=self.company,
            can_create_workers=False)
        api = APIClient()
        api.force_authenticate(user=limited)
        response = api.post(
            '/api/v1/accounts/users/',
            {'username': 'mx_denied', 'role': 'worker'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_manager_has_no_write_anywhere(self):
        """Менеджер нигде не пишет: заказ/клиент/задачу/склад — 403."""
        api = self._api('manager')
        checks = [
            ('/api/v1/orders/orders/', {'client': self.customer.pk, 'quantity': '1'}),
            ('/api/v1/clients/clients/', {'name': 'X'}),
            ('/api/v1/production/tasks/', {'title': 'X'}),
            ('/api/v1/warehouse/raw-materials/', {'name': 'X', 'unit': 'm2'}),
        ]
        for url, payload in checks:
            response = api.post(url, payload, format='json')
            self.assertEqual(response.status_code, 403, url)

    def test_worker_cannot_read_history_and_goods_receipts(self):
        """Работнику недоступны история склада и приходные документы (403)."""
        api = self._api('worker')
        self.assertEqual(api.get('/api/v1/warehouse/stock-movements/').status_code, 403)
        self.assertEqual(api.get('/api/v1/warehouse/goods-receipts/').status_code, 403)
        self.assertEqual(api.get('/api/v1/warehouse/recipes/').status_code, 403)

    def test_superadmin_has_no_business_data(self):
        """Супер-админ не видит бизнес-окна даже по прямым адресам API."""
        api = self._api('superadmin')
        for url in (
            '/api/v1/orders/orders/',
            '/api/v1/warehouse/raw-materials/',
            '/api/v1/production/tasks/',
            '/api/v1/clients/clients/',
            '/api/v1/finance/expenses/',
            '/api/v1/reports/analytics/sales/?period=month',
            '/api/v1/audit/logs/',
            '/api/v1/messaging/conversations/',
        ):
            self.assertEqual(api.get(url).status_code, 403, url)
