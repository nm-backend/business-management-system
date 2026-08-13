"""
Логин: сообщения о причинах отказа (мёртвые ветки LoginSerializer).

authenticate() не возвращает НЕАКТИВНЫХ пользователей (ModelBackend
user_can_authenticate), поэтому проверки is_active и блокировки компании в
LoginSerializer были недостижимы: заблокированный сотрудник и сотрудник
заблокированной компании получали одинаковый generic «Invalid username or
password». Теперь причина отказа видна.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company

LOGIN_URL = '/api/v1/accounts/login/'


class LoginMessageTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='MsgCo', is_active=True)
        self.worker = User.objects.create_user(username='msg_worker', password='WorkerPass123!',
                                               role=User.Role.WORKER, company=self.company)
        self.owner = User.objects.create_user(username='msg_owner', password='OwnerPass123!',
                                              role=User.Role.OWNER, company=self.company)

    def api(self):
        return APIClient()

    def _login(self, username, password):
        return self.api().post(LOGIN_URL, {'username': username, 'password': password},
                               format='json')

    def test_wrong_password_is_generic(self):
        resp = self._login('msg_worker', 'WrongPass123!')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Неверное имя пользователя или пароль', str(resp.data))

    def test_unknown_user_is_generic(self):
        resp = self._login('no_such_user', 'Whatever123!')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Неверное имя пользователя или пароль', str(resp.data))

    def test_deactivated_account_message(self):
        self.worker.is_active = False
        self.worker.save(update_fields=['is_active'])
        resp = self._login('msg_worker', 'WorkerPass123!')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Аккаунт деактивирован', str(resp.data))

    def test_blocked_company_message(self):
        # Р‘Р»РѕРєРёСЂРѕРІРєР° РєРѕРјРїР°РЅРёРё РєР°СЃРєР°РґРЅРѕ РіР°СЃРёС‚ СЃРѕС‚СЂСѓРґРЅРёРєРѕРІ (is_active=False) вЂ”
        # РѕР±Р° СЃРѕРѕР±С‰РµРЅРёСЏ С„РѕСЂРјР°Р»СЊРЅРѕ РІРµСЂРЅС‹, РЅРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РґРѕР»Р¶РµРЅ РїРѕРЅСЏС‚СЊ, С‡С‚Рѕ
        # РґРµР»Рѕ РІ РєРѕРјРїР°РЅРёРё.
        self.company.is_active = False
        self.company.save(update_fields=['is_active'])
        self.worker.is_active = False
        self.worker.save(update_fields=['is_active'])
        resp = self._login('msg_worker', 'WorkerPass123!')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Компания деактивирована', str(resp.data))

    def test_blocked_company_owner_gets_company_message(self):
        self.company.is_active = False
        self.company.save(update_fields=['is_active'])
        self.owner.is_active = False
        self.owner.save(update_fields=['is_active'])
        resp = self._login('msg_owner', 'OwnerPass123!')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Компания деактивирована', str(resp.data))

    def test_valid_login_still_works(self):
        resp = self._login('msg_worker', 'WorkerPass123!')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('tokens', resp.data)

