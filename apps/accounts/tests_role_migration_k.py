"""
Регрессия: удаление роли `manager`.

Роль убрана из модели (ТЗ знает только owner/admin/worker), но в уже работающих
базах могли остаться аккаунты с этим значением. Проверяем две независимые вещи:

1. Миграция 0016 реально переносит такие аккаунты в `worker`, не теряя их
   и не трогая остальных сотрудников.
2. Даже если строка с legacy-ролью появится в обход модели, систему это не
   сломает: роль просто не даёт никаких прав (fail-closed), а не выдаёт
   неявный доступ.
"""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from apps.accounts.models import User


class RoleChoicesTests(TestCase):
    """Список ролей в модели больше не содержит manager."""

    def test_manager_is_not_a_role_anymore(self):
        self.assertNotIn('manager', User.Role.values)
        self.assertEqual(
            sorted(User.Role.values),
            ['admin', 'owner', 'superadmin', 'worker'],
        )

    def test_legacy_manager_flags_are_all_false(self):
        # В обход choices (именно так выглядела бы уцелевшая строка) ставим
        # legacy-роль и убеждаемся, что она не включает ни одну бизнес-роль.
        user = User.objects.create_user(username='legacy', password='p')
        User.objects.filter(pk=user.pk).update(role='manager')
        user.refresh_from_db()

        self.assertFalse(user.is_owner)
        self.assertFalse(user.is_admin)
        self.assertFalse(user.is_worker)
        self.assertFalse(user.is_superadmin)


class ManagerRoleMigrationTests(TransactionTestCase):
    """
    Настоящий прогон миграции 0016 на данных, а не чтение её исходника.

    Схема откатывается до состояния ДО удаления роли, создаются аккаунты с
    role='manager', затем миграция применяется снова.
    """

    migrate_from = [('accounts', '0015_usersession')]
    migrate_to = [('accounts', '0016_alter_user_role')]

    def _migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor

    def test_legacy_manager_becomes_worker(self):
        executor = self._migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldUser = old_apps.get_model('accounts', 'User')

        legacy = OldUser.objects.create(username='legacy_manager', password='x', role='manager')
        admin = OldUser.objects.create(username='real_admin', password='x', role='admin')

        self._migrate(self.migrate_to)

        # Бывший manager существует и понижен до наименьших привилегий…
        legacy_after = User.objects.get(pk=legacy.pk)
        self.assertEqual(legacy_after.role, User.Role.WORKER)
        # …пароль и другие аккаунты не пострадали.
        self.assertTrue(legacy_after.is_active)
        self.assertEqual(User.objects.get(pk=admin.pk).role, User.Role.ADMIN)

    def test_no_manager_rows_survive_migration(self):
        executor = self._migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldUser = old_apps.get_model('accounts', 'User')
        OldUser.objects.create(username='legacy_manager_2', password='x', role='manager')

        self._migrate(self.migrate_to)

        self.assertFalse(User.objects.filter(role='manager').exists())
