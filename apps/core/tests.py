"""
Unit-тесты для apps.core: модели Currency / ExchangeRate и
permission-классы RBAC (apps.core.permissions).
"""
import datetime
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from apps.core import permissions as perms
from apps.core.models import Currency, ExchangeRate


def req(user):
    return SimpleNamespace(user=user)


def user(role='worker', authenticated=True, **extra):
    ns = SimpleNamespace(
        role=role,
        is_authenticated=authenticated,
        is_owner=(role == 'owner'),
        is_admin=(role == 'admin'),
        is_worker=(role == 'worker'),
    )
    for k, v in extra.items():
        setattr(ns, k, v)
    return ns


class CurrencyModelTests(TestCase):
    def test_str_representation(self):
        c = Currency(code='USD', name='US Dollar', symbol='$')
        self.assertEqual(str(c), 'USD ($)')

    def test_saving_default_currency_unsets_previous_default(self):
        first = Currency.objects.create(code='KGS', name='Som', symbol='с', is_default=True)
        second = Currency.objects.create(code='USD', name='Dollar', symbol='$', is_default=True)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)

    def test_non_default_save_leaves_existing_default(self):
        default = Currency.objects.create(code='KGS', name='Som', symbol='с', is_default=True)
        Currency.objects.create(code='EUR', name='Euro', symbol='€', is_default=False)
        default.refresh_from_db()
        self.assertTrue(default.is_default)


class ExchangeRateTests(TestCase):
    def setUp(self):
        self.usd = Currency.objects.create(code='USD', name='Dollar', symbol='$')
        self.kgs = Currency.objects.create(code='KGS', name='Som', symbol='с')

    def _rate(self, value, date):
        return ExchangeRate.objects.create(
            from_currency=self.usd, to_currency=self.kgs, rate=value, effective_date=date
        )

    def test_get_rate_returns_latest_on_or_before_date(self):
        self._rate('80.0', datetime.date(2024, 1, 1))
        newer = self._rate('90.0', datetime.date(2024, 6, 1))
        result = ExchangeRate.get_rate('USD', 'KGS', datetime.date(2024, 12, 31))
        self.assertEqual(result, newer)

    def test_get_rate_ignores_future_rates(self):
        older = self._rate('80.0', datetime.date(2024, 1, 1))
        self._rate('90.0', datetime.date(2024, 6, 1))
        result = ExchangeRate.get_rate('USD', 'KGS', datetime.date(2024, 3, 1))
        self.assertEqual(result, older)

    def test_get_rate_returns_none_when_no_match(self):
        self.assertIsNone(ExchangeRate.get_rate('EUR', 'KGS'))

    def test_str_representation(self):
        rate = self._rate('80.5', datetime.date(2024, 1, 1))
        self.assertIn('USD -> KGS', str(rate))


class AppsCorePermissionTests(SimpleTestCase):
    def test_is_owner_admin_worker(self):
        self.assertTrue(perms.IsOwner().has_permission(req(user('owner')), None))
        self.assertFalse(perms.IsOwner().has_permission(req(user('admin')), None))
        self.assertTrue(perms.IsAdmin().has_permission(req(user('admin')), None))
        self.assertTrue(perms.IsWorker().has_permission(req(user('worker')), None))

    def test_is_owner_or_admin(self):
        self.assertTrue(perms.IsOwnerOrAdmin().has_permission(req(user('owner')), None))
        self.assertTrue(perms.IsOwnerOrAdmin().has_permission(req(user('admin')), None))
        self.assertFalse(perms.IsOwnerOrAdmin().has_permission(req(user('worker')), None))

    def test_is_authenticated(self):
        self.assertTrue(perms.IsAuthenticated().has_permission(req(user()), None))
        self.assertFalse(perms.IsAuthenticated().has_permission(req(user(authenticated=False)), None))

    def test_financial_data_owner_only(self):
        self.assertTrue(perms.FinancialDataPermission().has_permission(req(user('owner')), None))
        self.assertFalse(perms.FinancialDataPermission().has_permission(req(user('worker')), None))

    def test_can_create_workers(self):
        perm = perms.CanCreateWorkers()
        self.assertTrue(perm.has_permission(req(user('owner')), None))
        self.assertTrue(perm.has_permission(req(user('admin', can_create_workers=True)), None))
        self.assertFalse(perm.has_permission(req(user('admin', can_create_workers=False)), None))
        self.assertFalse(perm.has_permission(req(user('worker', can_create_workers=True)), None))
        self.assertFalse(perm.has_permission(req(user(authenticated=False)), None))

    def test_can_write_to_owner(self):
        perm = perms.CanWriteToOwner()
        self.assertTrue(perm.has_permission(req(user('worker', can_write_to_owner=True)), None))
        self.assertFalse(perm.has_permission(req(user('worker', can_write_to_owner=False)), None))
        self.assertFalse(perm.has_permission(req(user(authenticated=False, can_write_to_owner=True)), None))

    def test_can_see_other_workers(self):
        perm = perms.CanSeeOtherWorkers()
        self.assertTrue(perm.has_permission(req(user('owner')), None))
        self.assertTrue(perm.has_permission(req(user('admin', can_see_other_workers=True)), None))
        self.assertFalse(perm.has_permission(req(user('admin', can_see_other_workers=False)), None))
        self.assertFalse(perm.has_permission(req(user('worker', can_see_other_workers=True)), None))

    def test_is_owner_or_assigned_worker_object_permission(self):
        perm = perms.IsOwnerOrAssignedWorker()
        owner = user('owner', uid=1)
        worker = user('worker', uid=2)
        other = user('worker', uid=3)
        obj_for_worker = SimpleNamespace(worker=worker)
        self.assertTrue(perm.has_object_permission(req(owner), None, obj_for_worker))
        self.assertTrue(perm.has_object_permission(req(worker), None, obj_for_worker))
        self.assertFalse(perm.has_object_permission(req(other), None, obj_for_worker))
        self.assertFalse(
            perm.has_object_permission(req(user(authenticated=False)), None, obj_for_worker)
        )

    def test_is_owner_or_assigned_admin(self):
        perm = perms.IsOwnerOrAssignedAdmin()
        self.assertTrue(perm.has_permission(req(user('owner')), None))
        self.assertTrue(perm.has_permission(req(user('admin')), None))
        self.assertFalse(perm.has_permission(req(user('worker')), None))
