"""
Этап E.5 — end-to-end проверка загрузки файлов (аватар) через реальный API.

Раньше validate_image_upload тестировался изолированно. Здесь проверяем, что
через multipart PATCH /me/ не-изображение отклоняется (400), а валидный PNG
проходит (200) — то есть валидатор реально подключён к боевому пути.
"""
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company


def _png_bytes(px=10):
    buf = BytesIO()
    Image.new('RGB', (px, px), (200, 120, 60)).save(buf, format='PNG')
    return buf.getvalue()


class AvatarUploadTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='UpCo')
        self.worker = User.objects.create_user(username='up_w', password='p',
                                                role=User.Role.WORKER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(user=self.worker)

    def test_valid_png_accepted(self):
        f = SimpleUploadedFile('a.png', _png_bytes(), content_type='image/png')
        resp = self.api.patch('/api/v1/accounts/me/', {'avatar': f}, format='multipart')
        self.assertEqual(resp.status_code, 200, resp.content[:300])

    def test_text_file_rejected(self):
        f = SimpleUploadedFile('a.txt', b'not an image at all', content_type='text/plain')
        resp = self.api.patch('/api/v1/accounts/me/', {'avatar': f}, format='multipart')
        self.assertEqual(resp.status_code, 400)

    def test_disguised_exe_as_png_rejected(self):
        # Исполняемый файл, переименованный в .png — Pillow не откроет → 400.
        f = SimpleUploadedFile('evil.png', b'MZ\x90\x00\x03fakeexe', content_type='image/png')
        resp = self.api.patch('/api/v1/accounts/me/', {'avatar': f}, format='multipart')
        self.assertEqual(resp.status_code, 400)
