"""
Custom permissions for role-based access control.

Этот модуль содержит кастомные permissions для Django REST Framework,
реализующие ролевую систему доступа (RBAC) и защиту финансовых данных.

ВАЖНО: Финансовые данные доступны только владельцу (owner).
"""
from rest_framework import permissions


class IsSuperAdmin(permissions.BasePermission):
    """
    Permission - платформенный супер-администратор.

    Управляет компаниями (арендаторами), не привязан к компании и не имеет
    доступа к бизнес-данным компаний.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superadmin)


class IsCompanyMember(permissions.BasePermission):
    """
    Permission - пользователь состоит в компании (арендаторе).

    База для всех бизнес-эндпоинтов: доступ только аутентифицированным
    пользователям owner/admin/worker, у которых задана company. Супер-админ
    (company=None) к данным компаний не допускается.
    """
    message = 'Вы должны принадлежать компании, чтобы получить доступ к этому ресурсу.'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and not user.is_superadmin
            and user.company_id is not None
        )


class IsOwner(permissions.BasePermission):
    """
    Permission - только владелец.

    Разрешает доступ только пользователям с ролью 'owner'.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_owner


class IsAdmin(permissions.BasePermission):
    """
    Permission - только администратор.

    Разрешает доступ только пользователям с ролью 'admin'.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_admin


class IsWorker(permissions.BasePermission):
    """
    Permission - только работник.

    Разрешает доступ только пользователям с ролью 'worker'.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_worker


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Permission - владелец или администратор.

    Разрешает доступ владельцу или администратору.
    """
    def has_permission(self, request, view):
        return request.user and (request.user.is_owner or request.user.is_admin)


class IsOwnerOrAdminOrManager(permissions.BasePermission):
    """
    Permission - владелец, администратор или менеджер.

    Менеджер получает ПРОСМОТР клиентов/заказов/производства (только чтение,
    без финансовых сумм). Изменяющие операции остаются за owner/admin
    (проверяется на уровне view через get_permissions), поэтому этот класс
    применяется к чтению (list/retrieve) и операционной аналитике.
    """
    def has_permission(self, request, view):
        return request.user and (
            request.user.is_owner or request.user.is_admin or request.user.is_manager
        )


class IsOwnerOrAdminOrWorker(permissions.BasePermission):
    """
    Permission - владелец, администратор или работник.

    Разрешает доступ owner/admin/worker, но НЕ менеджеру. Используется для
    изменяющих операций, которые менеджер выполнять не должен (например,
    создание задач и записей о работе в производстве).
    """
    def has_permission(self, request, view):
        return request.user and (
            request.user.is_owner or request.user.is_admin or request.user.is_worker
        )


class IsAuthenticated(permissions.BasePermission):
    """
    Permission - аутентифицированный пользователь.

    Разрешает доступ любому аутентифицированному пользователю.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class FinancialDataPermission(permissions.BasePermission):
    """
    Permission - защита финансовых данных.

    Разрешает доступ к финансовым данным только владельцу.
    Администраторы и работники не должны получать финансовые данные
    даже через API - сервер должен фильтровать их на уровне сериализаторов.

    Финансовые поля:
    - Цены (purchase_price, sale_price, cost_price)
    - Суммы заказов и оплат
    - Прибыль и расходы
    - Зарплаты и долги
    - Касса и финансы

    Используется в связке с сериализаторами, которые исключают
    финансовые поля для non-owner пользователей.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_owner


class CanCreateWorkers(permissions.BasePermission):
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


class CanWriteToOwner(permissions.BasePermission):
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


class CanSeeOtherWorkers(permissions.BasePermission):
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


class IsOwnerOrAssignedWorker(permissions.BasePermission):
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


class IsOwnerOrAssignedAdmin(permissions.BasePermission):
    """
    Permission - владелец или администратор.

    Разрешает доступ владельцу или администратору.
    """
    def has_permission(self, request, view):
        return request.user and (request.user.is_owner or request.user.is_admin)
