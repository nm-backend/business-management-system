"""
Этап A — регрессия доступа к производству.

Закрытая брешь (HIGH): WorkRecordViewSet и TaskViewSet были открытыми
ModelViewSet без get_permissions, а сериализаторы держали status/labor_cost
записываемыми. Работник мог PATCH'ем поставить своей записи status='confirmed'
и любой labor_cost, минуя confirm_work (без списания склада, без audit), а также
удалить запись/задачу. Плюс отрицательное quantity при подтверждении портило склад.

Эти тесты доказывают, что:
  - работник НЕ может изменить/удалить свою работу или задачу через API;
  - даже owner/admin не могут сменить status/labor_cost прямым PATCH (только confirm);
  - количество работы <= 0 отклоняется при создании и при подтверждении;
  - штатный путь (owner подтверждает работу) по-прежнему работает и двигает склад.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.production.models import WorkRecord, Task, TaskStatus
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem

AWAITING = WorkRecord.WorkStatus.AWAITING_CONFIRMATION
CONFIRMED = WorkRecord.WorkStatus.CONFIRMED


class _Base(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='ProdCo')
        self.owner = User.objects.create_user(username='pa_o', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.admin = User.objects.create_user(username='pa_a', password='p',
                                               role=User.Role.ADMIN, company=self.company)
        self.worker = User.objects.create_user(username='pa_w', password='p',
                                                role=User.Role.WORKER, company=self.company)
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Slab', quantity=Decimal('0'))
        self.material = RawMaterial.objects.create(
            company=self.company, name='Marble', quantity=Decimal('10'))
        recipe = Recipe.objects.create(company=self.company, product=self.product,
                                       name='Default', is_active=True)
        RecipeItem.objects.create(recipe=recipe, material=self.material,
                                  quantity_required=Decimal('2'), unit='sht')

        # Подтверждение работы требует заданной ставки: без неё оно
        # отказывает, чтобы работнику не начислялся молча ноль.
        from apps.finance.models import LaborRate
        for _p in FinishedProduct.objects.filter(company=self.company):
            LaborRate.objects.get_or_create(
                company=self.company, product=_p,
                operation=LaborRate.OperationType.OTHER,
                defaults={'rate_per_unit': Decimal('100'), 'unit': _p.unit})
    def api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def make_work(self, worker=None, quantity='2', status=AWAITING):
        return WorkRecord.objects.create(
            company=self.company, worker=worker or self.worker, product=self.product,
            quantity=Decimal(quantity), unit='sht', status=status)


class WorkRecordAccessTests(_Base):
    def test_worker_cannot_patch_own_work_to_confirmed(self):
        work = self.make_work()
        resp = self.api(self.worker).patch(
            f'/api/v1/production/works/{work.id}/',
            {'status': 'confirmed', 'labor_cost': '9999999'}, format='json')
        self.assertEqual(resp.status_code, 403)
        work.refresh_from_db()
        self.assertEqual(work.status, AWAITING)          # статус не изменён
        self.assertEqual(work.labor_cost, Decimal('0'))  # зарплата не изменена

    def test_worker_cannot_delete_own_work(self):
        work = self.make_work()
        resp = self.api(self.worker).delete(f'/api/v1/production/works/{work.id}/')
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(WorkRecord.objects.filter(pk=work.pk).exists())

    def test_owner_patch_cannot_change_status_or_labor_cost(self):
        """Owner может PATCH, но status/labor_cost read-only; правится только текст."""
        work = self.make_work()
        resp = self.api(self.owner).patch(
            f'/api/v1/production/works/{work.id}/',
            {'status': 'confirmed', 'labor_cost': '5000', 'comment': 'проверено'},
            format='json')
        self.assertEqual(resp.status_code, 200)
        work.refresh_from_db()
        self.assertEqual(work.status, AWAITING)          # не тронуто
        self.assertEqual(work.labor_cost, Decimal('0'))  # не тронуто
        self.assertEqual(work.comment, 'проверено')      # безопасное поле изменилось

    def test_create_negative_quantity_rejected(self):
        resp = self.api(self.worker).post(
            '/api/v1/production/works/',
            {'product': self.product.id, 'quantity': '-5', 'unit': 'sht'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_create_zero_quantity_rejected(self):
        resp = self.api(self.worker).post(
            '/api/v1/production/works/',
            {'product': self.product.id, 'quantity': '0', 'unit': 'sht'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_confirm_guards_nonpositive_quantity_and_keeps_stock(self):
        work = self.make_work(quantity='2')
        # Пробиваем в БД некорректное количество в обход сериализатора.
        WorkRecord.objects.filter(pk=work.pk).update(quantity=Decimal('-5'))
        resp = self.api(self.owner).post(f'/api/v1/production/works/{work.id}/confirm/')
        self.assertEqual(resp.status_code, 400)
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('10'))  # склад не тронут

    def test_owner_confirm_still_works_and_moves_stock(self):
        """Штатный путь не сломан: owner подтверждает, сырьё списывается."""
        work = self.make_work(quantity='2')
        resp = self.api(self.owner).post(f'/api/v1/production/works/{work.id}/confirm/')
        self.assertEqual(resp.status_code, 200)
        work.refresh_from_db()
        self.assertEqual(work.status, CONFIRMED)
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('6'))   # 10 - 2*2


class TaskAccessTests(_Base):
    def make_task(self, status=TaskStatus.ACCEPTED):
        return Task.objects.create(company=self.company, worker=self.worker,
                                   assigned_by=self.owner, status=status,
                                   is_self_assigned=True)

    def test_worker_cannot_patch_task_status(self):
        task = self.make_task()
        resp = self.api(self.worker).patch(
            f'/api/v1/production/tasks/{task.id}/',
            {'status': 'confirmed'}, format='json')
        self.assertEqual(resp.status_code, 403)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.ACCEPTED)  # не тронуто

    def test_worker_cannot_delete_task(self):
        task = self.make_task()
        resp = self.api(self.worker).delete(f'/api/v1/production/tasks/{task.id}/')
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(Task.objects.filter(pk=task.pk).exists())

    def test_owner_patch_cannot_change_task_status(self):
        task = self.make_task()
        resp = self.api(self.owner).patch(
            f'/api/v1/production/tasks/{task.id}/',
            {'status': 'confirmed'}, format='json')
        self.assertEqual(resp.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.ACCEPTED)  # read-only, не изменился
