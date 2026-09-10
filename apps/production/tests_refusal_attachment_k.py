"""
Фото-довод к отказу от задачи (макет «Вазифани рад этиш» → «Илова (ихтиёрий)»).

Раньше отказ принимал только причину и комментарий: работник не мог
приложить снимок бракованного материала, и админ разбирался на словах.
"""
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.production.models import Task, TaskStatus

TASKS = '/api/v1/production/tasks/'


def fake_image(name='proof.jpg'):
    """Минимальный валидный JPEG."""
    from PIL import Image

    buffer = BytesIO()
    Image.new('RGB', (4, 4), 'white').save(buffer, format='JPEG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/jpeg')


class TaskRefusalAttachmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='RefuseCo')
        cls.owner = User.objects.create_user(
            username='r_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='r_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def _pending_task(self, title='Подоконник'):
        return Task.objects.create(
            company=self.company, worker=self.worker, assigned_by=self.owner,
            status=TaskStatus.PENDING, title=title,
        )

    def test_refuse_with_attachment_multipart(self):
        """multipart с фото: вложение сохраняется вместе с исходным именем."""
        task = self._pending_task()
        response = self.api_as(self.worker).post(
            f'{TASKS}{task.id}/refuse/',
            {
                'reason': 'material_insufficient',
                'comment': 'Плита с трещиной',
                'attachment': fake_image(),
            },
            format='multipart',
        )
        self.assertEqual(response.status_code, 200, response.data)
        task.refresh_from_db()
        self.assertEqual(task.refusal_reason, 'material_insufficient')
        self.assertTrue(task.refusal_attachment)
        self.assertEqual(task.refusal_attachment_name, 'proof.jpg')
        # Вложение видно в сериализаторе — админ увидит его в карточке задачи.
        self.assertIn('refusal_attachment', response.data)
        self.assertTrue(response.data['refusal_attachment_name'])

    def test_refuse_without_attachment_json_unchanged(self):
        """Прежний JSON-путь (причина + комментарий) работает как раньше."""
        task = self._pending_task()
        response = self.api_as(self.worker).post(
            f'{TASKS}{task.id}/refuse/',
            {'reason': 'no_time', 'comment': 'Занят другим заказом'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        task.refresh_from_db()
        self.assertEqual(task.refusal_reason, 'no_time')
        self.assertFalse(task.refusal_attachment)
        self.assertEqual(task.refusal_attachment_name, '')

    def test_refuse_attachment_rejects_unsafe_extension(self):
        """Валидатор расширения блокирует, например, .exe."""
        task = self._pending_task()
        malicious = SimpleUploadedFile(
            'evil.exe', b'MZ...', content_type='application/octet-stream',
        )
        response = self.api_as(self.worker).post(
            f'{TASKS}{task.id}/refuse/',
            {'reason': 'other', 'attachment': malicious},
            format='multipart',
        )
        self.assertEqual(response.status_code, 400, response.data)
        task.refresh_from_db()
        # Отказ без валидного вложения не применён: файл не прошёл валидацию.
        self.assertEqual(task.refusal_reason, '')

    def test_refusal_attachment_visible_to_staff_in_task_list(self):
        """Админ видит вложение в списке задач (read-only поле)."""
        task = self._pending_task()
        self.api_as(self.worker).post(
            f'{TASKS}{task.id}/refuse/',
            {'reason': 'wrong_size', 'attachment': fake_image('size.jpg')},
            format='multipart',
        )
        response = self.api_as(self.owner).get(TASKS)
        self.assertEqual(response.status_code, 200)
        row = next(t for t in response.data['results'] if t['id'] == task.id)
        self.assertEqual(row['refusal_attachment_name'], 'size.jpg')

    def test_refusal_attachment_not_patchable(self):
        """refusal_attachment — read_only: прямым PATCH вложение не подменить."""
        task = self._pending_task()
        self.api_as(self.worker).post(
            f'{TASKS}{task.id}/refuse/',
            {'reason': 'wrong_size', 'attachment': fake_image('size.jpg')},
            format='multipart',
        )
        task.refresh_from_db()
        before = task.refusal_attachment.name
        response = self.api_as(self.owner).patch(
            f'{TASKS}{task.id}/',
            {'refusal_attachment': fake_image('hijack.jpg')},
            format='multipart',
        )
        self.assertIn(response.status_code, (200, 400), response.data)
        task.refresh_from_db()
        self.assertEqual(task.refusal_attachment.name, before)
        self.assertEqual(task.refusal_attachment_name, 'size.jpg')
