"""
Уведомления из ТЗ, которые объявлялись, но не отправлялись:

* MATERIAL_SHORTAGE админам/владельцу — при сдаче работы, на подтверждение
  которой сырья не хватит (считаем по сданному объёму: годное + брак);
* WORK_ACCRUED работнику — при подтверждении работы, вместе с суммой
  начисления («начислена личная работа»).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.finance.models import LaborRate
from apps.messaging.models import Notification
from apps.production.models import Task, TaskStatus, WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem

WORKS = '/api/v1/production/works/'
CONFIRM_TPL = '/api/v1/production/works/{id}/confirm/'


class ShortageAndAccrualNotificationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='NotifyCo')
        cls.owner = User.objects.create_user(
            username='n_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='n_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='n_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.product = FinishedProduct.objects.create(
            company=cls.company, name='Столешница', unit='sht', quantity=Decimal('0'),
        )
        cls.marble = RawMaterial.objects.create(
            company=cls.company, name='Мрамор ок', unit='m2', quantity=Decimal('1.40'),
        )
        cls.glue = RawMaterial.objects.create(
            company=cls.company, name='Елим (AB)', unit='kg', quantity=Decimal('5'),
        )
        cls.recipe = Recipe.objects.create(
            company=cls.company, product=cls.product, name='RCP-001', is_active=True,
        )
        RecipeItem.objects.create(
            recipe=cls.recipe, material=cls.marble,
            quantity_required=Decimal('2.20'), unit='m2',
        )
        RecipeItem.objects.create(
            recipe=cls.recipe, material=cls.glue,
            quantity_required=Decimal('0.30'), unit='kg',
        )
        LaborRate.objects.create(
            company=cls.company, product=cls.product,
            rate_per_unit=Decimal('100'),
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def _submit_work(self, quantity='1', defect='0'):
        task = Task.objects.create(
            company=self.company, worker=self.worker, assigned_by=self.owner,
            status=TaskStatus.ACCEPTED, title='Столешница',
        )
        response = self.api_as(self.worker).post(WORKS, {
            'task': task.id, 'product': self.product.id,
            'quantity': quantity, 'defect_quantity': defect, 'unit': 'sht',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return WorkRecord.objects.get(pk=response.data['id'])

    def _notifications(self, user, ntype):
        return list(Notification.objects.filter(user=user, type=ntype))

    # ── MATERIAL_SHORTAGE при сдаче работы ────────────────────────────────

    def test_submission_with_shortage_notifies_staff(self):
        """Сдача работы объёмом больше сырья → админ и владелец предупреждены."""
        self._submit_work(quantity='1')  # нужно 2.20 м², на складе 1.40
        for staff in (self.admin, self.owner):
            notes = self._notifications(staff, Notification.NotificationType.MATERIAL_SHORTAGE)
            self.assertEqual(len(notes), 1, staff.username)
            self.assertIn('Мрамор ок', notes[0].message)

    def test_submission_without_shortage_no_material_alert(self):
        """Сырья хватает (учитывается годное+брак) → уведомления о нехватке нет."""
        # 0.5 годных: требуется 1.10 м² — на складе 1.40 м², достаточно.
        work = self._submit_work(quantity='0.5')
        self.assertEqual(work.quantity, Decimal('0.5'))
        for staff in (self.admin, self.owner):
            self.assertEqual(
                self._notifications(staff, Notification.NotificationType.MATERIAL_SHORTAGE),
                [], staff.username,
            )

    def test_defect_included_in_shortage_check(self):
        """Брак тоже тратит сырьё: 0.5 годных + 1 брак = 3.30 м² > 1.40 м²."""
        self._submit_work(quantity='0.5', defect='1')
        notes = self._notifications(self.admin, Notification.NotificationType.MATERIAL_SHORTAGE)
        self.assertEqual(len(notes), 1)

    # ── WORK_ACCRUED при подтверждении ────────────────────────────────────

    def test_confirmation_notifies_worker_with_accrued_amount(self):
        """Подтверждение: работнику приходит и WORK_ACCRUED с суммой, и WORK_CONFIRMED."""
        # Сначала пополняем сырьё, чтобы подтверждение прошло.
        self.marble.quantity = Decimal('50')
        self.marble.save(update_fields=['quantity'])
        work = self._submit_work(quantity='2')
        response = self.api_as(self.admin).post(CONFIRM_TPL.format(id=work.id))
        self.assertEqual(response.status_code, 200, response.data)

        confirmed = self._notifications(self.worker, Notification.NotificationType.WORK_CONFIRMED)
        accrued = self._notifications(self.worker, Notification.NotificationType.WORK_ACCRUED)
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(len(accrued), 1)
        # Начислено = 2 шт × 100 = 200 (ставка из LaborRate).
        self.assertIn('200', accrued[0].message)
        self.assertEqual(accrued[0].title_key, 'notifications.work_accrued')

    def test_rejected_work_no_accrual_notification(self):
        """Отклонённая работа начисления не создаёт (и не уведомляет)."""
        self.marble.quantity = Decimal('50')
        self.marble.save(update_fields=['quantity'])
        work = self._submit_work(quantity='1')
        response = self.api_as(self.admin).post(
            f'/api/v1/production/works/{work.id}/reject/', {'reason': 'Переделать'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            self._notifications(self.worker, Notification.NotificationType.WORK_ACCRUED), [],
        )
