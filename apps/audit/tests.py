"""
Unit-тесты для приложения audit: сервисные функции (get_client_ip,
get_audit_object_type, normalize_audit_value, collect_model_changes,
collect_safe_request_changes, write_audit_log) и модель AuditLog.
"""
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.audit.services import (
    collect_model_changes,
    collect_safe_request_changes,
    get_audit_object_type,
    get_client_ip,
    normalize_audit_value,
    write_audit_log,
)


def fake_request(meta=None):
    return SimpleNamespace(META=meta or {})


class GetClientIpTests(SimpleTestCase):
    def test_none_request_returns_none(self):
        self.assertIsNone(get_client_ip(None))

    def test_prefers_x_forwarded_for(self):
        request = fake_request({'HTTP_X_FORWARDED_FOR': '1.1.1.1, 2.2.2.2', 'REMOTE_ADDR': '9.9.9.9'})
        self.assertEqual(get_client_ip(request), '1.1.1.1')

    def test_falls_back_to_remote_addr(self):
        request = fake_request({'REMOTE_ADDR': '9.9.9.9'})
        self.assertEqual(get_client_ip(request), '9.9.9.9')

    def test_returns_none_when_no_headers(self):
        self.assertIsNone(get_client_ip(fake_request({})))


class GetAuditObjectTypeTests(TestCase):
    def test_returns_app_label_and_model_name(self):
        user = User(username='x')
        self.assertEqual(get_audit_object_type(user), 'accounts.user')


class NormalizeAuditValueTests(SimpleTestCase):
    def test_decimal_becomes_string(self):
        self.assertEqual(normalize_audit_value(Decimal('12.50')), '12.50')

    def test_model_like_object_becomes_pk(self):
        self.assertEqual(normalize_audit_value(SimpleNamespace(pk=42)), 42)

    def test_primitives_unchanged(self):
        self.assertIsNone(normalize_audit_value(None))
        self.assertEqual(normalize_audit_value(True), True)
        self.assertEqual(normalize_audit_value(5), 5)
        self.assertEqual(normalize_audit_value(1.5), 1.5)
        self.assertEqual(normalize_audit_value('hi'), 'hi')

    def test_other_types_forced_to_str(self):
        self.assertEqual(normalize_audit_value(['a', 'b']), "['a', 'b']")


class CollectModelChangesTests(SimpleTestCase):
    def test_records_only_changed_fields(self):
        instance = SimpleNamespace(name='old', qty=5)
        changes = collect_model_changes(instance, {'name': 'new', 'qty': 5})
        self.assertEqual(changes, {'name': {'old': 'old', 'new': 'new'}})

    def test_normalizes_decimal_values(self):
        instance = SimpleNamespace(price=Decimal('1.00'))
        changes = collect_model_changes(instance, {'price': Decimal('2.00')})
        self.assertEqual(changes, {'price': {'old': '1.00', 'new': '2.00'}})

    def test_no_changes_returns_empty(self):
        instance = SimpleNamespace(name='same')
        self.assertEqual(collect_model_changes(instance, {'name': 'same'}), {})


class CollectSafeRequestChangesTests(TestCase):
    def test_only_allowed_fields_present_in_data_are_tracked(self):
        user = User.objects.create_user(username='u1', full_name='Old Name')
        data = {'full_name': 'New Name', 'password': 'secret'}
        changes = collect_safe_request_changes(user, data, allowed_fields=['full_name'])
        self.assertEqual(changes, {'full_name': {'old': 'Old Name', 'new': 'New Name'}})
        self.assertNotIn('password', changes)

    def test_field_not_in_data_is_skipped(self):
        user = User.objects.create_user(username='u2', full_name='Name')
        changes = collect_safe_request_changes(user, {}, allowed_fields=['full_name'])
        self.assertEqual(changes, {})


class WriteAuditLogTests(TestCase):
    def test_writes_log_with_target_and_actor(self):
        actor = User.objects.create_user(username='actor', role=User.Role.OWNER)
        target = User.objects.create_user(username='target', role=User.Role.WORKER)
        request = fake_request({'REMOTE_ADDR': '5.5.5.5', 'HTTP_USER_AGENT': 'pytest'})

        log = write_audit_log(
            action=AuditLog.Action.UPDATE,
            actor=actor,
            target=target,
            request=request,
        )

        self.assertEqual(log.actor, actor)
        self.assertEqual(log.actor_username, 'actor')
        self.assertEqual(log.actor_role, User.Role.OWNER)
        self.assertEqual(log.object_type, 'accounts.user')
        self.assertEqual(log.object_id, str(target.pk))
        self.assertEqual(log.ip_address, '5.5.5.5')
        self.assertEqual(log.user_agent, 'pytest')

    def test_unauthenticated_actor_is_not_stored(self):
        anon = SimpleNamespace(is_authenticated=False, username='anon', role='worker')
        log = write_audit_log(action=AuditLog.Action.LOGIN, actor=anon)
        self.assertIsNone(log.actor)
        self.assertEqual(log.actor_username, '')
        self.assertEqual(log.actor_role, '')

    def test_defaults_for_changes_and_metadata(self):
        log = write_audit_log(action=AuditLog.Action.SETUP_OWNER)
        self.assertEqual(log.changes, {})
        self.assertEqual(log.metadata, {})
        self.assertEqual(log.object_type, 'system')


class AuditLogModelTests(TestCase):
    def test_str_with_actor_and_repr(self):
        log = AuditLog(actor_username='alice', action='create', object_repr='Widget')
        self.assertEqual(str(log), 'alice create Widget')

    def test_str_defaults_to_system_and_object_type(self):
        log = AuditLog(actor_username='', action='login', object_repr='', object_type='system')
        self.assertEqual(str(log), 'system login system')
