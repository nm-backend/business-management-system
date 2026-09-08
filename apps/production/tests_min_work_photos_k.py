"""
Минимум фото при сдаче работы — настройка компании (решение по спорному пункту).

Макеты требуют «камида 1 та сурат» и «камида 2 та сурат», текст ТЗ минимума не
задаёт. Жёсткое правило заблокировало бы сдачу работы в цеху без камеры или
связи, поэтому минимум вынесен в настройку Company.min_work_photos: по
умолчанию 0 — поведение прежнее, владелец включает требование сам.
"""
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.production.models import Task, TaskStatus, WorkRecord
from apps.warehouse.models import FinishedProduct

WORKS = '/api/v1/production/works/'
SETTINGS = '/api/v1/companies/my-settings/'


def fake_image(name='photo.jpg'):
    """Минимальный валидный JPEG — достаточно для ImageField."""
    from PIL import Image

    buffer = BytesIO()
    Image.new('RGB', (4, 4), 'white').save(buffer, format='JPEG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/jpeg')


class MinWorkPhotosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='PhotoCo')
        cls.owner = User.objects.create_user(
            username='mp_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='mp_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='mp_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.product = FinishedProduct.objects.create(
            company=cls.company, name='Столешница', unit='sht', quantity=Decimal('0'),
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def _task(self):
        return Task.objects.create(
            company=self.company, worker=self.worker, assigned_by=self.owner,
            status=TaskStatus.ACCEPTED, title='Столешница',
        )

    def _submit(self, photos=0):
        payload = {
            'task': self._task().id, 'product': self.product.id,
            'quantity': '1', 'unit': 'sht',
        }
        if photos:
            payload['uploaded_photos'] = [fake_image(f'p{i}.jpg') for i in range(photos)]
            return self.api_as(self.worker).post(WORKS, payload, format='multipart')
        return self.api_as(self.worker).post(WORKS, payload, format='json')

    # ── Поведение по умолчанию ──────────────────────────────────────────────

    def test_default_zero_allows_work_without_photos(self):
        """По умолчанию требования нет — рабочий без камеры не застревает."""
        self.assertEqual(self.company.min_work_photos, 0)
        self.assertEqual(self._submit(photos=0).status_code, 201)

    # ── Включённое требование ───────────────────────────────────────────────

    def test_requirement_blocks_submission_without_photos(self):
        self.company.min_work_photos = 2
        self.company.save(update_fields=['min_work_photos'])

        response = self._submit(photos=0)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('uploaded_photos', response.data)
        self.assertEqual(WorkRecord.objects.count(), 0)

    def test_requirement_blocks_when_photos_not_enough(self):
        self.company.min_work_photos = 2
        self.company.save(update_fields=['min_work_photos'])
        self.assertEqual(self._submit(photos=1).status_code, 400)

    def test_enough_photos_pass(self):
        self.company.min_work_photos = 2
        self.company.save(update_fields=['min_work_photos'])

        response = self._submit(photos=2)
        self.assertEqual(response.status_code, 201, response.data)
        work = WorkRecord.objects.get(pk=response.data['id'])
        self.assertEqual(work.photos.count(), 2)

    # ── Настройка ───────────────────────────────────────────────────────────

    def test_owner_can_change_setting_and_it_persists(self):
        api = self.api_as(self.owner)
        response = api.patch(SETTINGS, {'min_work_photos': 2}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

        self.company.refresh_from_db()
        self.assertEqual(self.company.min_work_photos, 2)
        # Значение переживает повторное чтение — настройка сохранена, а не в сессии.
        self.assertEqual(api.get(SETTINGS).data['min_work_photos'], 2)

    def test_workers_can_read_setting(self):
        """Форма сдачи работы должна знать требуемый минимум."""
        self.company.min_work_photos = 3
        self.company.save(update_fields=['min_work_photos'])
        self.assertEqual(self.api_as(self.worker).get(SETTINGS).data['min_work_photos'], 3)

    def test_admin_cannot_change_setting(self):
        response = self.api_as(self.admin).patch(SETTINGS, {'min_work_photos': 5}, format='json')
        self.assertEqual(response.status_code, 403)
        self.company.refresh_from_db()
        self.assertEqual(self.company.min_work_photos, 0)

    def test_worker_cannot_change_setting(self):
        response = self.api_as(self.worker).patch(SETTINGS, {'min_work_photos': 5}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_absurd_value_rejected(self):
        response = self.api_as(self.owner).patch(SETTINGS, {'min_work_photos': 99}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_settings_are_tenant_scoped(self):
        """Настройки отдаются только своей компании — id чужой не принимается."""
        other = Company.objects.create(name='OtherPhotoCo', min_work_photos=7)
        data = self.api_as(self.owner).get(SETTINGS).data
        self.assertEqual(data['id'], self.company.id)
        self.assertNotEqual(data['min_work_photos'], other.min_work_photos)

    def test_setting_of_other_company_does_not_affect_us(self):
        Company.objects.create(name='StrictCo', min_work_photos=5)
        self.assertEqual(self._submit(photos=0).status_code, 201)
