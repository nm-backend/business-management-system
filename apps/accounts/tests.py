"""
Unit-тесты для приложения accounts: кастомный UserManager
(create_user / create_superuser / фильтры по ролям) и свойства модели User.
"""
from django.test import TestCase

from apps.accounts.models import User


class UserManagerTests(TestCase):
    def test_create_user_sets_password_and_defaults(self):
        user = User.objects.create_user(username='john', password='secret123')
        self.assertEqual(user.username, 'john')
        self.assertTrue(user.check_password('secret123'))
        # Роль по умолчанию — worker.
        self.assertEqual(user.role, User.Role.WORKER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_user_without_username_raises(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(username='', password='x')

    def test_create_user_accepts_extra_fields(self):
        user = User.objects.create_user(
            username='mary', password='p', role=User.Role.ADMIN, full_name='Mary M'
        )
        self.assertEqual(user.role, User.Role.ADMIN)
        self.assertEqual(user.full_name, 'Mary M')

    def test_create_superuser_defaults(self):
        owner = User.objects.create_superuser(username='boss', password='p')
        self.assertTrue(owner.is_staff)
        self.assertTrue(owner.is_superuser)
        self.assertEqual(owner.role, User.Role.OWNER)

    def test_create_superuser_respects_overrides(self):
        owner = User.objects.create_superuser(
            username='boss2', password='p', is_staff=False
        )
        self.assertFalse(owner.is_staff)

    def test_role_filters_return_only_active_matching_users(self):
        User.objects.create_user(username='o1', role=User.Role.OWNER)
        admin = User.objects.create_user(username='a1', role=User.Role.ADMIN)
        User.objects.create_user(username='w1', role=User.Role.WORKER)
        inactive_worker = User.objects.create_user(
            username='w2', role=User.Role.WORKER, is_active=False
        )

        self.assertEqual(list(User.objects.owners().values_list('username', flat=True)), ['o1'])
        self.assertEqual(list(User.objects.admins()), [admin])
        workers = User.objects.workers()
        self.assertIn('w1', workers.values_list('username', flat=True))
        self.assertNotIn(inactive_worker, workers)


class UserModelPropertyTests(TestCase):
    def test_role_properties(self):
        owner = User(username='o', role=User.Role.OWNER)
        admin = User(username='a', role=User.Role.ADMIN)
        worker = User(username='w', role=User.Role.WORKER)

        self.assertTrue(owner.is_owner)
        self.assertFalse(owner.is_admin)
        self.assertTrue(admin.is_admin)
        self.assertTrue(worker.is_worker)
        self.assertFalse(worker.is_owner)

    def test_display_role_returns_human_label(self):
        self.assertEqual(User(role=User.Role.OWNER).display_role, 'Egasi')
        self.assertEqual(User(role=User.Role.ADMIN).display_role, 'Administrator')
        self.assertEqual(User(role=User.Role.WORKER).display_role, 'Ishchi')

    def test_str_prefers_full_name(self):
        self.assertEqual(str(User(username='u', full_name='Full Name')), 'Full Name')

    def test_str_falls_back_to_username(self):
        self.assertEqual(str(User(username='u', full_name='')), 'u')
