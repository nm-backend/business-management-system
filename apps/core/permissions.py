"""
Custom permissions for role-based access control.

Этот модуль содержит кастомные permissions для Django REST Framework,
реализующие ролевую систему доступа (RBAC) и защиту финансовых данных.

ВАЖНО: Финансовые данные доступны только владельцу (owner).

SaaS GATE: бизнес-доступ требует активной подписки компании. Проверка живёт
в ДВУХ местах:
1. IsCompanyMember — базовый permission всех бизнес-эндпоинтов (owner/admin/
   worker/manager); замороженная/истёкшая компания получает 403 с понятным
   сообщением, даже если view переопределила permission_classes.
2. SubscriptionAccessPermission — подключён глобально (DEFAULT_PERMISSION_
   CLASSES) как страховка для view, которые могли бы его не использовать.
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
    Permission - пользователь состоит в компании (арендаторе) с активной подпиской.

    База для всех бизнес-эндпоинтов: доступ только аутентифицированным
    пользователям owner/admin/worker/manager, у которых задана company.
    Супер-админ (company=None) к данным компаний не допускается.

    Дополнительно проверяется SaaS-подписка: для замороженной (FROZEN),
    истёкшей (EXPIRED) или отменённой (CANCELLED) компании доступ к бизнес-
    данным закрыт на сервере. Аккаунты при этом НЕ деактивируются — владелец
    может войти и увидеть экран «Подписка истекла».
    """
    message = 'Подписка компании истекла или приостановлена. Обратитесь к администратору платформы.'

    def has_permission(self, request, view):
        user = request.user
        if not (
            user
            and user.is_authenticated
            and not user.is_superadmin
            and user.company_id is not None
        ):
            return False
        return user.company.is_subscription_active


class SubscriptionAccessPermission(permissions.BasePermission):
    """
    Permission - активная подписка компании (SaaS gate, страховочный слой).

    Подключён глобально (DEFAULT_PERMISSION_CLASSES): срабатывает на эндпоинты,
    которые по какой-то причине не используют IsCompanyMember. Супер-админ и
    сервисные эндпоинты (профиль, выход, push) НЕ блокируются: владелец
    замороженной компании должен иметь возможность войти и увидеть экран
    «Подписка истекла».
    """
    message = 'Подписка компании истекла или приостановлена. Обратитесь к администратору платформы.'

    _ALLOWED_PREFIXES = (
        '/api/v1/accounts/me',
        '/api/v1/accounts/logout',
        '/api/v1/accounts/push/',
        # Собственная подписка: владелец замороженной компании должен иметь
        # возможность увидеть состояние и запросить продление (это не
        # бизнес-данные, а платформенный контур).
        '/api/v1/companies/my-subscription',
    )

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return True  # анонимов обрабатывают другие permissions
        if user.is_superadmin or user.company_id is None:
            return True
        if request.path.startswith(self._ALLOWED_PREFIXES):
            return True
        # user.company кэшируется select_related('company') в JWT-аутентификации.
        return user.company.is_subscription_active


class IsOwner(permissions.BasePermission):
    """
    Permission - только владелец.

    Разрешает доступ только пользователям с ролью 'owner'.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_owner)


class IsAdmin(permissions.BasePermission):
    """
    Permission - только администратор.

    Разрешает доступ только пользователям с ролью 'admin'.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_admin)


class IsWorker(permissions.BasePermission):
    """
    Permission - только работник.

    Разрешает доступ только пользователям с ролью 'worker'.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_worker)


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Permission - владелец или администратор.

    Разрешает доступ владельцу или администратору.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.is_owner or request.user.is_admin))


class IsOwnerOrAdminOrManager(permissions.BasePermission):
    """
    Permission - владелец, администратор или менеджер.

    Менеджер получает ПРОСМОТР клиентов/заказов/производства (только чтение,
    без финансовых сумм). Изменяющие операции остаются за owner/admin
    (проверяется на уровне view через get_permissions), поэтому этот класс
    применяется к чтению (list/retrieve) и операционной аналитике.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (
            request.user.is_owner or request.user.is_admin or request.user.is_manager
        ))


class IsOwnerOrAdminOrWorker(permissions.BasePermission):
    """
    Permission - владелец, администратор или работник.

    Разрешает доступ owner/admin/worker, но НЕ менеджеру. Используется для
    изменяющих операций, которые менеджер выполнять не должен (например,
    создание задач и записей о работе в производстве).
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (
            request.user.is_owner or request.user.is_admin or request.user.is_worker
        ))


class IsAuthenticated(permissions.BasePermission):
    """
    Permission - аутентифицированный пользователь.

    Разрешает доступ любому аутентифицированному пользователю.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class FinancialDataPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_owner)


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
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.is_owner or request.user.is_admin))
