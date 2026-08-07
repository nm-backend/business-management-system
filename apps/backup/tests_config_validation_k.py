"""
PATCH /backup/config/: валидация входных полей.

Раньше значения уходили в БД сырыми: keep_last='abc' ронял сохранение в 500
(ValueError в БД-слое), is_enabled='yes' — тоже 500, а schedule='hourly'
молча сохранялся и в _sync_beat_schedule превращался в ЕЖЕЧАСНЫЙ бэкап
(маппинг по умолчанию MINUTES/1440).
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.backup.models import BackupConfig

URL = '/api/v1/backup/config/'


class BackupConfigValidationTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_user(username='bk_v_super', password='p',
                                                   role=User.Role.SUPERADMIN)
        self.api = APIClient()
        self.api.force_authenticate(user=self.superadmin)

    def test_keep_last_non_numeric_rejected(self):
        resp = self.api.patch(URL, {'keep_last': 'abc'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_keep_last_out_of_range_rejected(self):
        for value in (0, 366, -1):
            resp = self.api.patch(URL, {'keep_last': value}, format='json')
            self.assertEqual(resp.status_code, 400, f'keep_last={value}')

    def test_is_enabled_non_boolean_rejected(self):
        resp = self.api.patch(URL, {'is_enabled': 'yes'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_invalid_schedule_rejected_and_not_saved(self):
        resp = self.api.patch(URL, {'schedule': 'hourly'}, format='json')
        self.assertEqual(resp.status_code, 400)
        config = BackupConfig.objects.filter(company=None).first()
        if config is not None:
            self.assertNotEqual(config.schedule, 'hourly')

    def test_invalid_storage_rejected(self):
        resp = self.api.patch(URL, {'storage': 'carrier_pigeon'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_valid_patch_still_works(self):
        resp = self.api.patch(URL, {
            'keep_last': 14, 'schedule': 'weekly', 'is_enabled': True,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        config = BackupConfig.objects.get(company=None)
        self.assertEqual(config.keep_last, 14)
        self.assertEqual(config.schedule, 'weekly')
        self.assertTrue(config.is_enabled)
