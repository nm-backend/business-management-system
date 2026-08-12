"""
Аудит K: бэкап должен содержать media-файлы и переживать транзиентные сбои.

Находки: (1) в архив шёл только дамп БД — фото заказов в media жили только на
диске сервера; (2) max_retries=2 был мёртвой конфигурацией — self.retry() не
вызывался, задача падала с первого раза.
"""
import os
import tarfile
from types import SimpleNamespace
from unittest.mock import patch

from celery.exceptions import Retry as CeleryRetry
from django.conf import settings
from django.test import TestCase

from apps.backup.tasks import _backup_error_action, _bundle_backup, run_backup_task
from apps.companies.models import Company

from .models import BackupConfig, BackupLog


class BundleBackupTests(TestCase):
    def test_bundle_contains_dump_and_media(self):
        import tempfile

        tmpdir = tempfile.mkdtemp()
        dump = os.path.join(tmpdir, 'skladpro_backup_x.sql.gz')
        with open(dump, 'wb') as f:
            f.write(b'PGDUMP')

        media = os.path.join(tmpdir, 'media')
        os.makedirs(os.path.join(media, 'orders'))
        with open(os.path.join(media, 'orders', 'photo.jpg'), 'wb') as f:
            f.write(b'JPG')

        bundle, name = _bundle_backup(dump, os.path.basename(dump), media_root=media)

        self.assertTrue(name.endswith('.tar.gz'))
        with tarfile.open(bundle, 'r:gz') as tar:
            names = tar.getnames()
        self.assertIn('dump.sql.gz', names)
        self.assertTrue(any(n.startswith('media/') for n in names))

    def test_bundle_without_media_still_has_dump(self):
        import tempfile

        tmpdir = tempfile.mkdtemp()
        dump = os.path.join(tmpdir, 'skladpro_backup_x.sql.gz')
        with open(dump, 'wb') as f:
            f.write(b'PGDUMP')

        bundle, name = _bundle_backup(dump, os.path.basename(dump), media_root=None)

        with tarfile.open(bundle, 'r:gz') as tar:
            names = tar.getnames()
        self.assertIn('dump.sql.gz', names)
        self.assertFalse(any(n.startswith('media/') for n in names))


class BackupRetryTests(TestCase):
    def _self(self, retries=0, max_retries=2):
        return SimpleNamespace(
            request=SimpleNamespace(retries=retries),
            max_retries=max_retries,
            default_retry_delay=60,
        )

    def test_transient_failure_should_retry_with_message(self):
        message, should_retry = _backup_error_action(self._self(retries=0), RuntimeError('s3 down'))
        self.assertTrue(should_retry)
        self.assertIn('s3 down', message)
        self.assertIn('retry #1', message)
        self.assertIn('60s', message)

    def test_exhausted_retries_should_fail_silently(self):
        message, should_retry = _backup_error_action(self._self(retries=2), RuntimeError('still down'))
        self.assertFalse(should_retry)
        self.assertNotIn('retry', message)

    @patch('apps.backup.tasks._run_dump', side_effect=RuntimeError('s3 down'))
    def test_task_raises_retry_on_failure(self, _run_dump):
        self.company = Company.objects.create(name='BakCo')
        BackupConfig.objects.create(
            company=self.company, is_enabled=True, storage='s3',
            s3_access_key='long-access-key', s3_secret_key='long-secret-key', s3_bucket='b',
        )
        # Прямой вызов .run() не имеет celery-контекста: настоящий Task.retry()
        # в этом случае локально перевыполняет задачу. Подменяем его на метод,
        # который честно поднимает Retry, как это делает брокер.
        def fake_retry(*args, **kwargs):
            return (_ for _ in ()).throw(CeleryRetry('retry'))

        with patch('celery.app.task.Task.retry', side_effect=fake_retry):
            with self.assertRaises(CeleryRetry):
                run_backup_task.run(self.company.pk)
        log = BackupLog.objects.get(company=self.company)
        self.assertEqual(log.status, BackupLog.Status.FAILED)
        self.assertIn('s3 down', log.error_message)
