"""
Custom permission classes for role-based access control (RBAC).

Этот модуль содержит классы разрешений для Django REST Framework,
реализующие систему контроля доступа на основе ролей.

Роли в системе:
- owner: владелец бизнеса (полный доступ ко всем данным)
- admin: администратор (управление складом, работниками)
- worker: работник (ограниченный доступ к складу)

ВАЖНО: Финансовые данные (цены, себестоимость) доступны только owner.
"""
from rest_framework.permissions import BasePermission


class IsAuthenticated(BasePermission):
    """
    Кастомная проверка аутентификации — проверяет наличие user и is_authenticated.

    Отличается от DRF-шного IsAuthenticated тем, что дополнительно
    проверяет наличие объекта user (не только флаг is_authenticated).
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class IsOwner(BasePermission):
    """
    Разрешает доступ только пользователям с ролью 'owner'.

    Владелец имеет полный доступ ко всем данным системы,
    включая финансовую информацию и управление пользователями.

    Используется для:
    - Управления аккаунтами пользователей
    - Доступа к финансовым отчетам
    - Изменения критических настроек системы
    """
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'owner'
        )


class IsAdmin(BasePermission):
    """
    Разрешает доступ только пользователям с ролью 'admin'.

    Администратор может управлять складом и создавать работников,
    но не имеет доступа к финансовым данным.

    Используется для:
    - Управления складом (сырье и готовая продукция)
    - Создания аккаунтов работников
    - Управления производственными заданиями
    """
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'admin'
        )


class IsWorker(BasePermission):
    """
    Разрешает доступ только пользователям с ролью 'worker'.

    Работник имеет ограниченный доступ только к необходимым данным
    для выполнения своих обязанностей.

    Используется для:
    - Просмотра своих задач
    - Обновления статуса работ
    - Просмотра склада (без финансовых данных)
    """
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'worker'
        )


class IsOwnerOrAdmin(BasePermission):
    """
    Разрешает доступ пользователям с ролями 'owner' или 'admin'.

    Комбинированное разрешение для операций, которые могут выполнять
    как владелец, так и администратор.

    Используется для:
    - Создания и редактирования материалов на складе
    - Управления рецептами производства
    - Просмотра истории движений склада
    """
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ('owner', 'admin')
        )


class IsOwnerOrAdminOrWorker(BasePermission):
    """
    Разрешает доступ всем аутентифицированным пользователям с валидной ролью.

    Это базовое разрешение для большинства API endpoints.
    Гарантирует, что пользователь авторизован и имеет одну из ролей.

    Используется для:
    - Чтения общих данных склада
    - Просмотра информации о системе
    - Базового доступа к API
    """
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ('owner', 'admin', 'worker')
        )


class FinancialDataPermission(BasePermission):
    """
    Разрешает доступ к финансовым данным только владельцу.

    КРИТИЧЕСКИ ВАЖНО ДЛЯ БЕЗОПАСНОСТИ:
    Финансовые данные (цены закупки, себестоимость, прибыль)
    должны быть доступны только владельцу бизнеса.

    Используется для:
    - API endpoints, возвращающих финансовые поля
    - Отчетов о прибыли и убытках
    - Информации о зарплатах и выплатах

    ПРИМЕЧАНИЕ: В serializers.py финансовые поля исключаются
    для non-owner пользователей, но этот permission предоставляет
    дополнительный уровень защиты на уровне API.
    """
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'owner'
        )


class CanCreateWorkers(BasePermission):
    """
    Permission - может создавать работников.

    Разрешает создание работников только:
    - Владельцу
    - Администратору с разрешением can_create_workers
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_owner:
            return True
        if request.user.is_admin and request.user.can_create_workers:
            return True
        return False


class CanWriteToOwner(BasePermission):
    """
    Permission - может писать владельцу.

    Разрешает отправку сообщений владельцу только:
    - Администратору с разрешением can_write_to_owner
    - Работнику с разрешением can_write_to_owner
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.can_write_to_owner


class CanSeeOtherWorkers(BasePermission):
    """
    Permission - может видеть других работников.

    Разрешает просмотр других работников только:
    - Владельцу
    - Администратору с разрешением can_see_other_workers
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_owner:
            return True
        if request.user.is_admin and request.user.can_see_other_workers:
            return True
        return False


class IsOwnerOrAssignedWorker(BasePermission):
    """
    Permission - владелец или назначенный работник.

    Разрешает доступ владельцу или работнику, которому назначена задача.
    Используется для задач и работ.
    """
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_owner:
            return True
        if hasattr(obj, 'worker') and obj.worker == request.user:
            return True
        return False


class IsOwnerOrAssignedAdmin(BasePermission):
    """
    Permission - владелец или администратор.

    Разрешает доступ владельцу или администратору.
    """
    def has_permission(self, request, view):
        return request.user and (request.user.is_owner or request.user.is_admin)
