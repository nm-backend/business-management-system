"""
Bootstrap платформенного супер-администратора (команда ensure_superuser).

На Railway/Render нет интерактивной консоли, поэтому первый супер-админ
создаётся из переменных окружения. Команда должна быть идемпотентной: её
вызывают на каждом деплое.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import User

ENV = {
    'DJANGO_SUPERUSER_USERNAME': 'platform_admin',
    'DJANGO_SUPERUSER_PASSWORD': 'Str0ng!Pass9',
    'DJANGO_SUPERUSER_FULL_NAME': 'Платформенный админ',
}


def run():
    out = StringIO()
    call_command('ensure_superuser', stdout=out)
    return out.getvalue()


class EnsureSuperuserTests(TestCase):
    def test_creates_superadmin_with_admin_access(self):
        with self.settings():
            import os
            os.environ.update(ENV)
            try:
                run()
            finally:
                for k in ENV:
                    os.environ.pop(k, None)

        user = User.objects.get(username='platform_admin')
        self.assertEqual(user.role, User.Role.SUPERADMIN)
        self.assertTrue(user.is_staff)        # доступ к /admin/
        self.assertTrue(user.is_superuser)
        self.assertIsNone(user.company_id)
        self.assertTrue(user.check_password('Str0ng!Pass9'))
        self.assertNotIn('Str0ng!Pass9', user.password)   # пароль захеширован

    def test_idempotent_second_run_creates_nothing(self):
        import os
        os.environ.update(ENV)
        try:
            run()
            second = run()
        finally:
            for k in ENV:
                os.environ.pop(k, None)
        self.assertIn('уже существует', second)
        self.assertEqual(User.objects.filter(role=User.Role.SUPERADMIN).count(), 1)

    def test_without_env_vars_does_nothing(self):
        import os
        for k in ENV:
            os.environ.pop(k, None)
        out = run()
        self.assertIn('не заданы', out)
        self.assertFalse(User.objects.exists())
