"""
Регрессия обхода blocked_by_owner через админ-действие (аудит K, находка #1).

API-путь toggle_active восстанавливает только blocked_by_owner=False, но
админ-действие _set_active делало update(is_active=True) для ВСЕХ пользователей
компании — воскрешая работника, которого владелец заблокировал индивидуально.
"""
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase

from apps.accounts.models import User
from apps.companies.admin import CompanyAdmin
from apps.companies.models import Company


class AdminUnblockBypassTests(TestCase):
    def _request(self):
        req = RequestFactory().post('/admin/')
        setattr(req, 'session', {})
        setattr(req, '_messages', FallbackStorage(req))
        return req

    def test_unblock_company_does_not_resurrect_owner_blocked_worker(self):
        company = Company.objects.create(name='KAdmin1', is_active=True)
        worker = User.objects.create_user(username='k_ab_w', password='p',
                                          role=User.Role.WORKER, company=company)
        # Владелец индивидуально заблокировал работника.
        worker.is_active = False
        worker.blocked_by_owner = True
        worker.save(update_fields=['is_active', 'blocked_by_owner'])

        admin_obj = CompanyAdmin(Company, AdminSite())
        admin_obj.unblock_companies(self._request(), Company.objects.filter(pk=company.pk))

        worker.refresh_from_db()
        self.assertFalse(worker.is_active)      # НЕ должен воскреснуть
        self.assertTrue(worker.blocked_by_owner)

    def test_unblock_company_reactivates_normal_worker(self):
        company = Company.objects.create(name='KAdmin2', is_active=True)
        worker = User.objects.create_user(username='k_ab_w2', password='p',
                                          role=User.Role.WORKER, company=company)
        # Деактивирован блокировкой компании, но НЕ владельцем.
        worker.is_active = False
        worker.save(update_fields=['is_active'])

        admin_obj = CompanyAdmin(Company, AdminSite())
        admin_obj.unblock_companies(self._request(), Company.objects.filter(pk=company.pk))

        worker.refresh_from_db()
        self.assertTrue(worker.is_active)       # обычный работник восстановлен
