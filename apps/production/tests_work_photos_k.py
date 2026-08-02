"""
Галерея фото выполненной работы.

Макет «Ишни тасдиқлаш»: администратор принимает решение, глядя на снимки
(«Суратлар» — миниатюры и «+2»). В коде фото было одно и в интерфейсе не
показывалось нигде: карточка работы рисовала номер, товар, количество и
кнопки, а тега изображения в ней не было ни одного. Админ подтверждал
вслепую, хотя подтверждение меняет склад и начисляет рабочему деньги.

Правило по решению владельца мягкое: работу без фото принимаем, админ видит
это и решает сам.
"""
import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.production.models import WorkPhoto, WorkRecord
from apps.warehouse.models import FinishedProduct

WORKS = '/api/v1/production/works/'

def png(name):
    """Настоящее изображение: ImageField проверяет содержимое через Pillow."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new('RGB', (4, 4), color=(200, 200, 200)).save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


class WorkPhotoGalleryTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='PhotoCo', is_active=True)
        self.owner = User.objects.create_user(username='ph_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.admin = User.objects.create_user(username='ph_admin', password='p',
                                              role=User.Role.ADMIN, company=self.company)
        self.worker = User.objects.create_user(username='ph_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('0'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.worker)

    def submit(self, photos=(), **extra):
        data = {'product': self.product.id, 'quantity': '2', 'unit': 'dona'}
        data.update(extra)
        if photos:
            data['uploaded_photos'] = list(photos)
        return self.api.post(WORKS, data, format='multipart')

    def test_several_photos_are_stored(self):
        resp = self.submit([png('a.png'), png('b.png'), png('c.png')])
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        work = WorkRecord.objects.get(pk=resp.json()['id'] if 'id' in resp.json() else None) \
            if 'id' in resp.json() else WorkRecord.objects.latest('id')
        self.assertEqual(WorkPhoto.objects.filter(work=work).count(), 3)

    def test_work_without_photos_is_still_accepted(self):
        """Правило мягкое: цех не должен вставать из-за отсутствия камеры."""
        self.assertEqual(self.submit().status_code, 201)

    def test_admin_sees_the_gallery(self):
        self.submit([png('a.png'), png('b.png')])
        api = APIClient()
        api.force_authenticate(self.admin)
        row = (api.get(WORKS).json()['results'])[0]
        self.assertEqual(len(row['photos']), 2)
        self.assertTrue(row['photos'][0]['image'].endswith('.png'))
        # деньги админу по-прежнему не отдаём
        self.assertNotIn('labor_cost', row)

    def test_owner_sees_gallery_and_money(self):
        self.submit([png('a.png')])
        api = APIClient()
        api.force_authenticate(self.owner)
        row = (api.get(WORKS).json()['results'])[0]
        self.assertEqual(len(row['photos']), 1)
        self.assertIn('labor_cost', row)

    def test_single_legacy_photo_lands_in_gallery(self):
        """Старое одиночное поле не должно оставаться невидимым."""
        resp = self.api.post(WORKS, {
            'product': self.product.id, 'quantity': '1', 'unit': 'dona',
            'photo': png('legacy.png'),
        }, format='multipart')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        work = WorkRecord.objects.latest('id')
        self.assertEqual(WorkPhoto.objects.filter(work=work).count(), 1)

    def test_foreign_company_work_is_not_listed(self):
        self.submit([png('a.png')])
        other = Company.objects.create(name='Чужая', is_active=True)
        stranger = User.objects.create_user(username='ph_stranger', password='p',
                                            role=User.Role.OWNER, company=other)
        api = APIClient()
        api.force_authenticate(stranger)
        self.assertEqual(api.get(WORKS).json()['results'], [])

    def test_broken_file_rejected(self):
        bad = SimpleUploadedFile('a.png', b'not an image', content_type='image/png')
        self.assertEqual(self.submit([bad]).status_code, 400)
