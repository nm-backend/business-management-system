"""
API views for authentication and user management.

Этот модуль содержит view классы Django REST Framework для:
- Аутентификации (login, logout, token refresh)
- Начальной настройки системы (создание владельца)
- Управления пользователями (CRUD с RBAC)
- Управления профилем текущего пользователя

Все действия записываются в audit log для безопасности и отслеживания.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from apps.audit.models import AuditLog
from apps.audit.services import collect_model_changes, write_audit_log
from core.permissions import IsOwner, IsOwnerOrAdmin
from .models import User
from .serializers import (
    UserSerializer, UserSelfUpdateSerializer, UserCreateSerializer, UserLimitedSerializer,
    LoginSerializer, ChangePasswordSerializer, SetupOwnerSerializer,
    LanguageSerializer,
)


class SetupCheckView(APIView):
    """
    API для проверки необходимости начальной настройки.

    Позволяет фронтенду определить, нужно ли показывать страницу
    начальной настройки (создание владельца).

    Endpoint: GET /api/v1/accounts/setup/check/

    Права доступа:
        AllowAny - доступен без аутентификации

    Возвращает:
        {'setup_required': bool} - True если владелец еще не создан
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """
        Проверяет, существует ли владелец в системе.

        Возвращает:
            Response с {'setup_required': True/False}
        """
        owner_exists = User.objects.filter(role='owner').exists()
        return Response({'setup_required': not owner_exists})


class SetupOwnerView(APIView):
    """
    API для создания владельца системы (начальная настройка).

    Используется только при первом запуске для создания первого
    пользователя с ролью owner. После создания владельца этот endpoint
    блокируется.

    Endpoint: POST /api/v1/accounts/setup/owner/

    Права доступа:
        AllowAny - доступен без аутентификации (только если owner не существует)

    Тело запроса:
        {
            "username": "string",
            "password": "string",
            "password_confirm": "string",
            "full_name": "string",
            "phone": "string" (опционально)
        }

    Возвращает:
        {
            "user": UserSerializer data,
            "tokens": {"access": "jwt_token", "refresh": "jwt_token"}
        }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        """
        Создает владельца системы и возвращает JWT токены.

        Проверяет, что владелец еще не существует, валидирует данные,
        создает пользователя с ролью owner и генерирует JWT токены.

        Возвращает:
            Response с данными пользователя и токенами (201 Created)
            или ошибку 403 если владелец уже существует
        """
        if User.objects.filter(role='owner').exists():
            return Response({'error': 'Owner already exists. Setup is complete.'}, status=status.HTTP_403_FORBIDDEN)
        serializer = SetupOwnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        write_audit_log(
            action=AuditLog.Action.SETUP_OWNER,
            actor=user,
            target=user,
            request=request,
        )
        refresh = RefreshToken.for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            'tokens': {'refresh': str(refresh), 'access': str(refresh.access_token)}
        }, status=status.HTTP_201_CREATED)

class LoginView(APIView):
    """
    API для аутентификации пользователя.

    Проверяет учетные данные и возвращает JWT токены для доступа к API.

    Endpoint: POST /api/v1/accounts/login/

    Права доступа:
        AllowAny - доступен без аутентификации

    Тело запроса:
        {
            "username": "string",
            "password": "string"
        }

    Возвращает:
        {
            "user": UserSerializer data,
            "tokens": {"access": "jwt_token", "refresh": "jwt_token"}
        }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        """
        Аутентифицирует пользователя и генерирует JWT токены.

        Валидирует username/password, создает JWT токены (access и refresh),
        записывает действие в audit log.

        Возвращает:
            Response с данными пользователя и токенами
        """
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        write_audit_log(
            action=AuditLog.Action.LOGIN,
            actor=user,
            target=user,
            request=request,
        )
        refresh = RefreshToken.for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            'tokens': {'refresh': str(refresh), 'access': str(refresh.access_token)}
        })


class LogoutView(APIView):
    """
    API для выхода из системы.

    Блокирует refresh токен в blacklist, предотвращая его повторное использование.

    Endpoint: POST /api/v1/accounts/logout/

    Права доступа:
        IsAuthenticated - требует аутентификации

    Тело запроса:
        {
            "refresh": "jwt_token" (опционально)
        }

    Возвращает:
        205 Reset Content
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Выходит из системы и блокирует refresh токен.

        Добавляет refresh токен в blacklist для предотвращения повторного использования.
        Записывает действие в audit log.

        Возвращает:
            205 Reset Content
        """
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            pass
        write_audit_log(
            action=AuditLog.Action.LOGOUT,
            actor=request.user,
            target=request.user,
            request=request,
        )
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(APIView):
    """
    API для получения и обновления профиля текущего пользователя.

    Позволяет пользователю просматривать и редактировать свой профиль.

    Endpoint: GET/PATCH /api/v1/accounts/me/

    Права доступа:
        IsAuthenticated - требует аутентификации

    GET возвращает:
        UserSerializer data с полной информацией о текущем пользователе

    PATCH принимает:
        {
            "full_name": "string",
            "phone": "string",
            "email": "string",
            "avatar": "file",
            "language": "uz_cyrl|ru"
        }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Возвращает данные текущего пользователя.

        Возвращает:
            Response с UserSerializer data
        """
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        """
        Обновляет профиль текущего пользователя.

        Пользователь может редактировать только свои личные данные.
        Изменения записываются в audit log.

        Возвращает:
            Response с обновленными данными пользователя
        """
        serializer = UserSelfUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = collect_model_changes(request.user, serializer.validated_data)
        serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=request.user,
                target=request.user,
                changes=changes,
                request=request,
            )
        return Response(UserSerializer(request.user).data)


class ChangePasswordView(APIView):
    """
    API для изменения пароля текущего пользователя.

    Позволяет пользователю изменить свой пароль после проверки текущего.

    Endpoint: POST /api/v1/accounts/me/password/

    Права доступа:
        IsAuthenticated - требует аутентификации

    Тело запроса:
        {
            "old_password": "string",
            "new_password": "string"
        }

    Возвращает:
        {"message": "Password changed successfully"}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Изменяет пароль текущего пользователя.

        Проверяет старый пароль, устанавливает новый пароль,
        записывает действие в audit log.

        Возвращает:
            Response с сообщением об успехе
        """
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save()
        write_audit_log(
            action=AuditLog.Action.CHANGE_PASSWORD,
            actor=request.user,
            target=request.user,
            request=request,
        )
        return Response({'message': 'Password changed successfully'})


class ChangeLanguageView(APIView):
    """
    API для изменения языка интерфейса.

    Позволяет пользователю выбрать предпочитаемый язык (узбекский или русский).

    Endpoint: POST /api/v1/accounts/me/language/

    Права доступа:
        IsAuthenticated - требует аутентификации

    Тело запроса:
        {
            "language": "uz_cyrl|ru"
        }

    Возвращает:
        {"language": "uz_cyrl|ru", "message": "Language updated"}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Изменяет язык интерфейса пользователя.

        Обновляет поле language в модели User, записывает изменение в audit log.

        Возвращает:
            Response с новым языком и сообщением об успехе
        """
        serializer = LanguageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        old_language = request.user.language
        request.user.language = serializer.validated_data['language']
        request.user.save(update_fields=['language'])
        write_audit_log(
            action=AuditLog.Action.CHANGE_LANGUAGE,
            actor=request.user,
            target=request.user,
            changes={
                'language': {
                    'old': old_language,
                    'new': request.user.language,
                }
            },
            request=request,
        )
        return Response({'language': request.user.language, 'message': 'Language updated'})

class UserViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления аккаунтами пользователей через RBAC.

    Реализует полный CRUD для пользователей с контролем доступа на основе ролей.
    Владелец может управлять всеми пользователями, администратор - только работниками.

    RBAC (Role-Based Access Control):
    - Owner: полный доступ ко всем пользователям, может создавать admin и worker
    - Admin: может создавать только worker (при наличии разрешения can_create_workers)
    - Worker: нет доступа к управлению пользователями

    Endpoint: /api/v1/accounts/users/

    Actions:
    - GET /api/v1/accounts/users/ - список пользователей (фильтруется по роли)
    - POST /api/v1/accounts/users/ - создание пользователя (owner/admin)
    - GET /api/v1/accounts/users/{id}/ - детали пользователя
    - PATCH /api/v1/accounts/users/{id}/ - обновление (только owner)
    - DELETE /api/v1/accounts/users/{id}/ - ЗАПРЕЩЕНО (используйте toggle_active)
    - POST /api/v1/accounts/users/{id}/toggle_active/ - активация/деактивация (owner)
    - POST /api/v1/accounts/users/{id}/reset_password/ - сброс пароля (owner)
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Возвращает queryset пользователей в зависимости от роли текущего пользователя.

        Логика фильтрации:
        - Owner: видит всех пользователей
        - Admin: видит только работников
        - Worker: не видит никого (пустой queryset)

        Возвращает:
            QuerySet - отфильтрованный список пользователей
        """
        user = self.request.user
        if user.is_owner:
            return User.objects.all()
        elif user.is_admin:
            return User.objects.filter(role='worker')
        return User.objects.none()

    def get_serializer_class(self):
        """
        Выбирает сериализатор в зависимости от действия и роли пользователя.

        Логика выбора:
        - create: UserCreateSerializer (для создания с паролем)
        - owner: UserSerializer (полные данные)
        - admin: UserLimitedSerializer (без административных полей)

        Возвращает:
            Serializer class - соответствующий сериализатор
        """
        if self.action == 'create':
            return UserCreateSerializer
        if self.request.user.is_owner:
            return UserSerializer
        return UserLimitedSerializer

    def get_permissions(self):
        """
        Устанавливает разрешения в зависимости от действия.

        Логика разрешений:
        - create: IsOwnerOrAdmin (владелец или администратор)
        - update/partial_update/destroy: IsOwner (только владелец)
        - остальные: IsAuthenticated (любой аутентифицированный)

        Возвращает:
            list - список permission классов
        """
        if self.action == 'create':
            return [IsOwnerOrAdmin()]
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsOwner()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        """
        Создает пользователя с учетом роли создателя и бизнес-правил.

        Логика создания:
        - Owner: может создавать admin и worker (но не второго owner)
        - Admin: может создавать только worker при наличии can_create_workers
        - Worker: не может создавать пользователей

        Бизнес-правила:
        - Администраторы не могут создавать других администраторов
        - Администраторы создают работников без административных прав
        - Владелец не может создать второго владельца

        Записывает действие в audit log.
        """
        user = self.request.user
        requested_role = serializer.validated_data.get('role', User.Role.WORKER)

        if user.is_owner:
            # Владелец может создавать admin и worker
            if requested_role == User.Role.OWNER:
                raise ValidationError({'role': 'Owner account already exists'})
            created_user = serializer.save()
            write_audit_log(
                action=AuditLog.Action.CREATE,
                actor=user,
                target=created_user,
                metadata={'created_role': created_user.role},
                request=self.request,
            )
            return

        if user.is_admin:
            # Администратор может создавать только workers
            if not user.can_create_workers:
                raise PermissionDenied('You do not have permission to create workers')
            if requested_role != User.Role.WORKER:
                raise PermissionDenied('Administrators can create only worker accounts')
            created_user = serializer.save(
                role=User.Role.WORKER,
                can_write_to_owner=False,
                can_create_workers=False,
                can_see_other_workers=False,
            )
            write_audit_log(
                action=AuditLog.Action.CREATE,
                actor=user,
                target=created_user,
                metadata={'created_role': created_user.role},
                request=self.request,
            )
            return

        raise PermissionDenied('You do not have permission to create accounts')

    def perform_update(self, serializer):
        """
        Обновляет пользователя и записывает изменения в audit log.

        Только владелец может обновлять пользователей.
        Изменения полей записываются в audit log для отслеживания истории.
        """
        changes = collect_model_changes(serializer.instance, serializer.validated_data)
        updated_user = serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=self.request.user,
                target=updated_user,
                changes=changes,
                request=self.request,
            )

    def destroy(self, request, *args, **kwargs):
        """
        ЗАПРЕЩЕНО: физическое удаление пользователей.

        Вместо удаления используйте action toggle_active для деактивации аккаунта.
        Это сохраняет историю и позволяет восстановить аккаунт при необходимости.

        Исключение:
            MethodNotAllowed - удаление запрещено
        """
        raise MethodNotAllowed('DELETE', detail='Account deletion is prohibited. Block the account instead.')

    @action(detail=True, methods=['post'], permission_classes=[IsOwner])
    def toggle_active(self, request, pk=None):
        """
        Активирует или деактивирует аккаунт пользователя.

        Используется вместо удаления для блокировки аккаунта с возможностью восстановления.
        Владелец не может быть деактивирован.

        Endpoint: POST /api/v1/accounts/users/{id}/toggle_active/

        Права доступа:
            IsOwner - только владелец

        Возвращает:
            {'is_active': bool} - новое состояние активности
        """
        user = self.get_object()
        if user.role == 'owner':
            return Response({'error': 'Cannot deactivate owner account'}, status=status.HTTP_400_BAD_REQUEST)
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        write_audit_log(
            action=AuditLog.Action.ACTIVATE if user.is_active else AuditLog.Action.DEACTIVATE,
            actor=request.user,
            target=user,
            changes={'is_active': {'old': not user.is_active, 'new': user.is_active}},
            request=request,
        )
        return Response({'is_active': user.is_active})

    @action(detail=True, methods=['post'], permission_classes=[IsOwner])
    def reset_password(self, request, pk=None):
        """
        Сбрасывает пароль пользователя на новый.

        Позволяет владельцу установить новый пароль для любого пользователя.
        Используется когда пользователь забыл пароль или нужно сменить его принудительно.

        Endpoint: POST /api/v1/accounts/users/{id}/reset_password/

        Права доступа:
            IsOwner - только владелец

        Тело запроса:
            {"new_password": "string"} (минимум 6 символов)

        Возвращает:
            {'message': 'Password reset successfully'}
        """
        user = self.get_object()
        new_password = request.data.get('new_password')
        if not new_password or len(new_password) < 6:
            return Response({'error': 'Password must be at least 6 characters'}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.save()
        write_audit_log(
            action=AuditLog.Action.RESET_PASSWORD,
            actor=request.user,
            target=user,
            request=request,
        )
        return Response({'message': 'Password reset successfully'})
