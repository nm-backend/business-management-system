"""
Custom permissions for role-based access control.

Этот модуль содержит кастомные permissions для Django REST Framework,
реализующие ролевую систему доступа (RBAC) и защиту финансовых данных.

ВАЖНО: Финансовые данные доступны только владельцу (owner).
"""
from rest_framework import permissions


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
