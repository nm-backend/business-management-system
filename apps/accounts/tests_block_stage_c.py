"""
Этап C — регрессия модели блокировки и инвалидации токенов.

Закрываем 4 дыры:
  1. redeem_access_key не должен реактивировать заблокированного сотрудника.
  2. Разблокировка компании не должна снимать индивидуальные блокировки.
  3. is_active нельзя менять обычным PATCH — только через toggle_active.
  4. Смена/сброс пароля, блокировка пользователя и блокировка компании должны
     инвалидировать все refresh-токены (SimpleJWT blacklist).

Плюс тесты на попытки обхода.
"""
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from django.test import TestCase

from apps.accounts.models import User, AccessKey
from apps.accounts.access_keys import issue_access_key
from apps.companies.models import Company


class _Base(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='CblockCo')
        self.owner = User.objects.create_user(username='c_o', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='c_w', password='p',
                                                role=User.Role.WORKER, company=self.company)
        self.worker2 = User.objects.create_user(username='c_w2', password='p',
                                                 role=User.Role.WORKER, company=self.company)
        self.superadmin = User.objects.create_user(username='c_sa', password='p',
                                                    role=User.Role.SUPERADMIN, company=None)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def refresh_rejected(self, refresh):
        resp = APIClient().post('/api/v1/accounts/token/refresh/',
                                {'refresh': str(refresh)}, format='json')
        return resp.status_code == 401


class RedeemBlockedTests(_Base):
    def _invite(self, user):
        """Переводит сотрудника в статус приглашённого (без пароля)."""
        user.set_unusable_password()
        user.save()

    def test_redeem_does_not_reactivate_blocked_user(self):
        self._invite(self.worker)
        key = issue_access_key(user=self.worker, created_by=self.owner)  # ключ выдан до блокировки
        self.worker.is_active = False
        self.worker.blocked_by_owner = True
        self.worker.save(update_fields=['is_active', 'blocked_by_owner'])

        resp = APIClient().post('/api/v1/accounts/access-key/redeem/', {
            'access_key': key.key, 'new_password': 'newpass12345'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.worker.refresh_from_db()
        self.assertFalse(self.worker.is_active)  # блокировка сохранилась

    def test_issue_key_to_blocked_user_raises(self):
        # Блокировка админом = blocked_by_owner (так её ставит toggle_active).
        self._invite(self.worker)
        self.worker.is_active = False
        self.worker.blocked_by_owner = True
        self.worker.save(update_fields=['is_active', 'blocked_by_owner'])
        with self.assertRaises(ValueError):
            issue_access_key(user=self.worker, created_by=self.owner)

    def test_issue_key_to_invited_inactive_user_still_works(self):
        """Приглашённый (is_active=False, но НЕ blocked_by_owner) — ключ выдаётся."""
        self._invite(self.worker)
        self.worker.is_active = False  # до-активационный статус, не блокировка
        self.worker.save(update_fields=['is_active'])
        key = issue_access_key(user=self.worker, created_by=self.owner)
        self.assertIsNotNone(key)


class CompanyReactivationTests(_Base):
    def test_company_reactivation_preserves_individual_block(self):
        # 1) Владелец индивидуально блокирует worker.
        r = self.api(self.owner).post(f'/api/v1/accounts/users/{self.worker.id}/toggle_active/')
        self.assertEqual(r.status_code, 200)
        self.worker.refresh_from_db()
        self.assertFalse(self.worker.is_active)
        self.assertTrue(self.worker.blocked_by_owner)

        # 2) Супер-админ блокирует компанию (все is_active=False).
        r = self.api(self.superadmin).post(f'/api/v1/companies/{self.company.id}/toggle_active/')
        self.assertEqual(r.status_code, 200)
        # 3) Супер-админ разблокирует компанию.
        r = self.api(self.superadmin).post(f'/api/v1/companies/{self.company.id}/toggle_active/')
        self.assertEqual(r.status_code, 200)

        self.worker.refresh_from_db()
        self.worker2.refresh_from_db()
        self.assertFalse(self.worker.is_active)   # индивидуальная блокировка НЕ снята
        self.assertTrue(self.worker2.is_active)   # обычный сотрудник восстановлен


class IsActiveNotWritableTests(_Base):
    def test_is_active_not_writable_via_user_patch(self):
        resp = self.api(self.owner).patch(
            f'/api/v1/accounts/users/{self.worker2.id}/',
            {'is_active': False}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.worker2.refresh_from_db()
        self.assertTrue(self.worker2.is_active)  # read-only: PATCH проигнорирован


class TokenInvalidationTests(_Base):
    def test_password_change_blacklists_refresh(self):
        refresh = RefreshToken.for_user(self.worker)
        resp = self.api(self.worker).post('/api/v1/accounts/me/password/', {
            'old_password': 'p', 'new_password': 'newpass12345'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.refresh_rejected(refresh))

    def test_password_reset_blacklists_refresh(self):
        refresh = RefreshToken.for_user(self.worker)
        resp = self.api(self.owner).post(
            f'/api/v1/accounts/users/{self.worker.id}/reset_password/',
            {'new_password': 'newpass12345'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.refresh_rejected(refresh))

    def test_password_reset_rejects_weak_password(self):
        """Сброс пароля обязан проходить те же валидаторы, что и смена."""
        for weak in ('aaaaaaaa', '12345678', 'password'):
            resp = self.api(self.owner).post(
                f'/api/v1/accounts/users/{self.worker.id}/reset_password/',
                {'new_password': weak}, format='json')
            self.assertEqual(resp.status_code, 400, f'слабый пароль {weak} прошёл: {resp.content[:200]}')
        self.worker.refresh_from_db()
        self.assertTrue(self.worker.check_password('p'), 'пароль изменился при отклонённом сбросе')

    def test_block_user_blacklists_refresh(self):
        refresh = RefreshToken.for_user(self.worker)
        resp = self.api(self.owner).post(
            f'/api/v1/accounts/users/{self.worker.id}/toggle_active/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.refresh_rejected(refresh))

    def test_company_block_blacklists_user_refresh(self):
        refresh = RefreshToken.for_user(self.worker)
        resp = self.api(self.superadmin).post(
            f'/api/v1/companies/{self.company.id}/toggle_active/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.refresh_rejected(refresh))

    def test_valid_refresh_still_works_without_block(self):
        """Позитивный контроль: без блокировки/смены пароля refresh работает."""
        refresh = RefreshToken.for_user(self.worker2)
        resp = APIClient().post('/api/v1/accounts/token/refresh/',
                                {'refresh': str(refresh)}, format='json')
        self.assertEqual(resp.status_code, 200)
