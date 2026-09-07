"""
Тесты вложений в чате (файлы и фото в переписке — макеты «Ички чат»).

До этого фронтенд отправлял файл в multipart-поле attachment, а бэкенд его
молча выбрасывал: у ChatMessage не было поля, а ChatMessageCreateSerializer
принимал только conversation и content. Сообщение из одного файла (без
подписи) вообще падало с 400 «Сообщение не может быть пустым».

Покрываем:
- отправку файла с текстом и без текста;
- запрет пустого сообщения (без текста и без файла);
- белый список расширений и лимит размера;
- превью беседы для сообщения-файла (📎 имя файла);
- уведомление о личном сообщении с файлом;
- изоляцию: чужой пользователь не может отправить файл в чужую беседу.
"""
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.messaging.models import ChatMessage, Conversation, Notification
from apps.messaging.services import ensure_general_conversation, get_or_create_direct

MEDIA = tempfile.mkdtemp(prefix='chat-attach-test-')


def png_bytes():
    """Минимальный валидный PNG (1×1)."""
    return (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06'
        b'\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05'
        b'\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    )


@override_settings(MEDIA_ROOT=MEDIA)
class ChatAttachmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='Granit')
        cls.owner = User.objects.create_user(
            username='owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.other_company = Company.objects.create(name='Marmar')
        cls.stranger = User.objects.create_user(
            username='stranger', password='pw', role=User.Role.OWNER, company=cls.other_company,
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.general = ensure_general_conversation(self.company)

    # ── отправка ────────────────────────────────────────────────────────────

    def test_message_with_file_and_text(self):
        upload = SimpleUploadedFile('chizma.pdf', b'%PDF-1.4 test', content_type='application/pdf')
        response = self.client.post('/api/v1/messaging/messages/', {
            'conversation': self.general.id,
            'content': 'Чизмани юбордим',
            'attachment': upload,
        }, format='multipart')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['content'], 'Чизмани юбордим')
        self.assertEqual(response.data['attachment_name'], 'chizma.pdf')
        self.assertTrue(response.data['attachment'].endswith('.pdf'))

        message = ChatMessage.objects.get(pk=response.data['id'])
        self.assertTrue(message.attachment)
        self.assertEqual(message.attachment_name, 'chizma.pdf')

    def test_message_with_file_only(self):
        """Файл без подписи — раньше это был 400, теперь допустимо."""
        upload = SimpleUploadedFile('photo.png', png_bytes(), content_type='image/png')
        response = self.client.post('/api/v1/messaging/messages/', {
            'conversation': self.general.id,
            'attachment': upload,
        }, format='multipart')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['content'], '')
        self.assertEqual(response.data['attachment_name'], 'photo.png')

    def test_empty_message_still_rejected(self):
        response = self.client.post('/api/v1/messaging/messages/', {
            'conversation': self.general.id,
            'content': '   ',
        }, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ChatMessage.objects.count(), 0)

    def test_plain_json_message_still_works(self):
        """Обычные текстовые сообщения не должны сломаться."""
        response = self.client.post('/api/v1/messaging/messages/', {
            'conversation': self.general.id,
            'content': 'Салом',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data['attachment'])

    # ── валидация файла ─────────────────────────────────────────────────────

    def test_dangerous_extension_rejected(self):
        """.html/.svg исполняют скрипт при открытии — хранимый XSS."""
        upload = SimpleUploadedFile('evil.html', b'<script>alert(1)</script>', content_type='text/html')
        response = self.client.post('/api/v1/messaging/messages/', {
            'conversation': self.general.id,
            'attachment': upload,
        }, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ChatMessage.objects.count(), 0)

    def test_too_large_file_rejected(self):
        upload = SimpleUploadedFile('big.pdf', b'x' * (10 * 1024 * 1024 + 1), content_type='application/pdf')
        response = self.client.post('/api/v1/messaging/messages/', {
            'conversation': self.general.id,
            'attachment': upload,
        }, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ChatMessage.objects.count(), 0)

    # ── превью и уведомления ────────────────────────────────────────────────

    def test_conversation_preview_shows_file_name(self):
        upload = SimpleUploadedFile('smeta.xlsx', b'PK\x03\x04smeta', content_type='application/vnd.ms-excel')
        self.client.post('/api/v1/messaging/messages/', {
            'conversation': self.general.id,
            'attachment': upload,
        }, format='multipart')

        response = self.client.get('/api/v1/messaging/conversations/')
        self.assertEqual(response.status_code, 200)
        conversations = response.data['results'] if 'results' in response.data else response.data
        general = next(c for c in conversations if c['kind'] == Conversation.Kind.GENERAL)
        self.assertEqual(general['last_message']['content'], '📎 smeta.xlsx')

    def test_direct_file_message_creates_notification_with_file_name(self):
        conversation, _ = get_or_create_direct(self.company, self.owner, self.worker)
        upload = SimpleUploadedFile('akt.pdf', b'%PDF-1.4', content_type='application/pdf')
        response = self.client.post('/api/v1/messaging/messages/', {
            'conversation': conversation.id,
            'attachment': upload,
        }, format='multipart')
        self.assertEqual(response.status_code, 201, response.data)

        notification = Notification.objects.get(
            user=self.worker, type=Notification.NotificationType.NEW_MESSAGE,
        )
        self.assertEqual(notification.message, '📎 akt.pdf')

    # ── изоляция ────────────────────────────────────────────────────────────

    def test_foreign_company_cannot_attach_to_our_conversation(self):
        client = APIClient()
        client.force_authenticate(self.stranger)
        upload = SimpleUploadedFile('spy.pdf', b'%PDF-1.4', content_type='application/pdf')
        response = client.post('/api/v1/messaging/messages/', {
            'conversation': self.general.id,
            'attachment': upload,
        }, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ChatMessage.objects.count(), 0)
