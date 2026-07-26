"""
Бэкап — операция супер-администратора платформы (аудит нового кода).

НАЙДЕННАЯ ДЫРА: pg_dump выгружает базу ЦЕЛИКОМ (данные всех компаний), а
эндпоинты стояли под [IsCompanyMember, IsOwner]. Владелец компании A мог
включить бэкап со СВОИМИ ключами S3 / Telegram-ботом и получить дамп с
клиентами, заказами, финансами и хешами паролей компании B.

Теперь настройка/запуск/логи доступны только супер-админу платформы, а
конфигурация одна на платформу (company=None).
"""
import json

from django.test import TestCase
from django_celery_beat.models import PeriodicTask
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.backup.models import BackupConfig, BackupLog
from apps.backup.tasks import _redact_secrets
from apps.companies.models import Company

CONFIG_URL = '/api/v1/backup/config/'
TRIGGER_URL = '/api/v1/backup/trigger/'
LOGS_URL = '/api/v1/backup/logs/'


class BackupAccessControlTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='BkpCo', is_active=True)
        self.owner = User.objects.create_user(username='bkp_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.admin = User.objects.create_user(username='bkp_admin', password='p',
                                              role=User.Role.ADMIN, company=self.company)
        self.worker = User.objects.create_user(username='bkp_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.superadmin = User.objects.create_user(username='bkp_super', password='p',
                                                   role=User.Role.SUPERADMIN)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_company_users_cannot_reach_backup_at_all(self):
        # Владелец компании больше НЕ имеет доступа: дамп содержит чужие данные.
        for user in (self.owner, self.admin, self.worker):
            for url in (CONFIG_URL, LOGS_URL):
                resp = self.api(user).get(url)
                self.assertEqual(resp.status_code, 403, f'{user.username} -> GET {url}')
            resp = self.api(user).post(TRIGGER_URL, {}, format='json')
            self.assertEqual(resp.status_code, 403, f'{user.username} -> POST {TRIGGER_URL}')

    def test_company_owner_cannot_enable_backup_with_own_credentials(self):
        resp = self.api(self.owner).patch(CONFIG_URL, {
            'is_enabled': True, 'storage': 'telegram',
            'telegram_bot_token': 'attacker-token', 'telegram_chat_id': '123',
        }, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(BackupConfig.objects.filter(is_enabled=True).exists())

    def test_superadmin_can_read_platform_config(self):
        resp = self.api(self.superadmin).get(CONFIG_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['is_enabled'])
        # Секреты наружу не отдаются — только флаги наличия.
        self.assertIn('has_s3_key', resp.json())
        self.assertNotIn('s3_secret_key', resp.json())
        self.assertNotIn('telegram_bot_token', resp.json())
        # Конфигурация платформенная, не привязана к компании.
        config = BackupConfig.objects.get()
        self.assertIsNone(config.company_id)

    def test_superadmin_logs_are_platform_scoped(self):
        BackupLog.objects.create(company=self.company, status=BackupLog.Status.SUCCESS)
        platform_log = BackupLog.objects.create(company=None, status=BackupLog.Status.SUCCESS)
        resp = self.api(self.superadmin).get(LOGS_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([row['id'] for row in resp.json()], [platform_log.id])


class BackupScheduleTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_user(username='bkp_super2', password='p',
                                                   role=User.Role.SUPERADMIN)

    def api(self):
        c = APIClient()
        c.force_authenticate(user=self.superadmin)
        return c

    def test_enabling_creates_valid_periodic_task_args(self):
        resp = self.api().patch(CONFIG_URL, {'is_enabled': True, 'schedule': 'daily'},
                                format='json')
        self.assertEqual(resp.status_code, 200)
        task = PeriodicTask.objects.get(name='backup-platform')
        self.assertEqual(task.task, 'apps.backup.tasks.run_backup_task')
        # args ДОЛЖНЫ быть валидным JSON: раньше f-string давал '[None, null]'
        # и beat не мог запустить задачу.
        self.assertEqual(json.loads(task.args), [None, None])

    def test_disabling_removes_periodic_task(self):
        self.api().patch(CONFIG_URL, {'is_enabled': True}, format='json')
        self.assertTrue(PeriodicTask.objects.filter(name='backup-platform').exists())
        self.api().patch(CONFIG_URL, {'is_enabled': False}, format='json')
        self.assertFalse(PeriodicTask.objects.filter(name='backup-platform').exists())


class RedactSecretsTests(TestCase):
    def test_error_message_strips_token_and_keys(self):
        config = BackupConfig(
            telegram_bot_token='123456:SECRET-BOT-TOKEN',
            s3_secret_key='SECRET-S3-KEY',
            s3_access_key='ACCESS-KEY-ID',
        )
        raw = ('HTTPSConnectionPool: POST https://api.telegram.org/bot123456:'
               'SECRET-BOT-TOKEN/sendDocument failed; key=SECRET-S3-KEY id=ACCESS-KEY-ID')
        cleaned = _redact_secrets(raw, config)
        self.assertNotIn('SECRET-BOT-TOKEN', cleaned)
        self.assertNotIn('SECRET-S3-KEY', cleaned)
        self.assertNotIn('ACCESS-KEY-ID', cleaned)
        self.assertIn('***', cleaned)
