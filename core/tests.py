"""
Unit-тесты для core-утилит: deep_merge, format_currency, get_locale,
классов пагинации и permission-классов RBAC (core.permissions).
"""
from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from core import permissions as core_permissions
from core.pagination import LargePagination, SmallPagination, StandardPagination
from core.utils import deep_merge, format_currency, get_locale


def make_request(user):
    """Возвращает объект-заглушку request с указанным пользователем."""
    return SimpleNamespace(user=user)


def make_user(role='worker', authenticated=True, **extra):
    """Возвращает объект-заглушку пользователя для permission-тестов."""
    is_superadmin = role == 'superadmin'
    return SimpleNamespace(
        role=role,
        is_authenticated=authenticated,
        is_owner=role == 'owner',
        is_admin=role == 'admin',
        is_worker=role == 'worker',
        is_manager=role == 'manager',
        is_superadmin=is_superadmin,
        **extra,
    )


class DeepMergeTests(SimpleTestCase):
    def test_merges_nested_dicts_recursively(self):
        base = {'a': 1, 'b': {'x': 10}}
        override = {'b': {'y': 20}, 'c': 3}
        self.assertEqual(
            deep_merge(base, override),
            {'a': 1, 'b': {'x': 10, 'y': 20}, 'c': 3},
        )

    def test_override_takes_priority_for_scalars(self):
        self.assertEqual(deep_merge({'a': 1}, {'a': 2}), {'a': 2})

    def test_non_dict_override_replaces_dict(self):
        self.assertEqual(deep_merge({'a': {'x': 1}}, {'a': 5}), {'a': 5})

    def test_does_not_mutate_inputs(self):
        base = {'a': {'x': 1}}
        override = {'a': {'y': 2}}
        deep_merge(base, override)
        self.assertEqual(base, {'a': {'x': 1}})
        self.assertEqual(override, {'a': {'y': 2}})

    def test_empty_override_returns_copy_of_base(self):
        base = {'a': 1}
        result = deep_merge(base, {})
        self.assertEqual(result, base)
        self.assertIsNot(result, base)


class FormatCurrencyTests(SimpleTestCase):
    def test_none_returns_empty_string(self):
        self.assertEqual(format_currency(None), '')

    def test_default_uses_space_thousands_separator_and_truncates(self):
        self.assertEqual(format_currency(12345.67), '12 345 som')

    def test_large_integer_formatting(self):
        self.assertEqual(format_currency(1234567), '1 234 567 som')

    def test_custom_symbol_and_decimals(self):
        self.assertEqual(format_currency(12345.67, '$', 2), '12 345.67 $')

    def test_zero_amount(self):
        self.assertEqual(format_currency(0), '0 som')


class GetLocaleTests(SimpleTestCase):
    def test_default_locale_returns_non_empty_dict(self):
        data = get_locale()
        self.assertIsInstance(data, dict)
        self.assertIn('app', data)

    def test_unknown_language_falls_back_to_uz_cyrl(self):
        self.assertEqual(get_locale('does_not_exist'), get_locale('uz_cyrl'))

    def test_ru_locale_overrides_translations(self):
        uz = get_locale('uz_cyrl')
        ru = get_locale('ru')
        self.assertEqual(set(uz.keys()), set(ru.keys()))
        self.assertNotEqual(uz['auth']['login'], ru['auth']['login'])


class PaginationTests(SimpleTestCase):
    def test_pagination_class_attributes(self):
        self.assertEqual(StandardPagination.page_size, 20)
        self.assertEqual(StandardPagination.max_page_size, 100)
        self.assertEqual(SmallPagination.page_size, 10)
        self.assertEqual(SmallPagination.max_page_size, 50)
        self.assertEqual(LargePagination.page_size, 50)
        self.assertEqual(LargePagination.max_page_size, 200)

    def test_page_size_query_param_configured(self):
        for cls in (StandardPagination, SmallPagination, LargePagination):
            self.assertEqual(cls.page_size_query_param, 'page_size')

    def test_client_can_override_page_size_within_limit(self):
        paginator = StandardPagination()
        request = APIRequestFactory().get('/?page_size=5')
        from rest_framework.request import Request
        size = paginator.get_page_size(Request(request))
        self.assertEqual(size, 5)

    def test_client_cannot_exceed_max_page_size(self):
        paginator = SmallPagination()
        request = APIRequestFactory().get('/?page_size=9999')
        from rest_framework.request import Request
        size = paginator.get_page_size(Request(request))
        self.assertEqual(size, SmallPagination.max_page_size)


class CorePermissionTests(SimpleTestCase):
    def test_is_owner(self):
        perm = core_permissions.IsOwner()
        self.assertTrue(perm.has_permission(make_request(make_user('owner')), None))
        self.assertFalse(perm.has_permission(make_request(make_user('admin')), None))

    def test_is_admin(self):
        perm = core_permissions.IsAdmin()
        self.assertTrue(perm.has_permission(make_request(make_user('admin')), None))
        self.assertFalse(perm.has_permission(make_request(make_user('worker')), None))

    def test_is_worker(self):
        perm = core_permissions.IsWorker()
        self.assertTrue(perm.has_permission(make_request(make_user('worker')), None))
        self.assertFalse(perm.has_permission(make_request(make_user('owner')), None))

    def test_is_owner_or_admin(self):
        perm = core_permissions.IsOwnerOrAdmin()
        self.assertTrue(perm.has_permission(make_request(make_user('owner')), None))
        self.assertTrue(perm.has_permission(make_request(make_user('admin')), None))
        self.assertFalse(perm.has_permission(make_request(make_user('worker')), None))

    def test_is_owner_or_admin_or_manager(self):
        perm = core_permissions.IsOwnerOrAdminOrManager()
        for role in ('owner', 'admin', 'manager'):
            self.assertTrue(perm.has_permission(make_request(make_user(role)), None), role)
        self.assertFalse(perm.has_permission(make_request(make_user('worker')), None))

    def test_is_owner_or_admin_or_worker(self):
        perm = core_permissions.IsOwnerOrAdminOrWorker()
        for role in ('owner', 'admin', 'worker'):
            self.assertTrue(perm.has_permission(make_request(make_user(role)), None))
        self.assertFalse(perm.has_permission(make_request(make_user('ghost')), None))

    def test_financial_data_permission_owner_only(self):
        perm = core_permissions.FinancialDataPermission()
        self.assertTrue(perm.has_permission(make_request(make_user('owner')), None))
        self.assertFalse(perm.has_permission(make_request(make_user('admin')), None))

    def test_unauthenticated_denied(self):
        perm = core_permissions.IsOwner()
        self.assertFalse(perm.has_permission(make_request(AnonymousUser()), None))
