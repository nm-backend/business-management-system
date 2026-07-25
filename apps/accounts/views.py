"""
API views for authentication and user management.

Этот модуль содержит view классы Django REST Framework для:
- Аутентификации (login, logout, token refresh)
- Начальной настройки системы (создание владельца)
- Управления пользователями (CRUD с RBAC)
- Управления профилем текущего пользователя

Все действия записываются в audit log для безопасности и отслеживания.
"""
from django.conf import settings as django_settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken as SimpleJWTRefreshToken
from .fingerprint_jwt import RefreshToken as FingerprintRefreshToken
from apps.audit.models import AuditLog
from apps.audit.services import collect_model_changes, write_audit_log
from apps.core.permissions import IsCompanyMember
from apps.core.validators import parse_int_param
from core.permissions import IsOwner, IsOwnerOrAdmin
from . import two_factor
from .access_keys import issue_access_key, redeem_access_key, verify_access_key
from .push_service import send_push_to_company
from .token_utils import blacklist_all_tokens
from .models import AccessKey, PushSubscription, Skill, User
from .serializers import (
    UserSerializer, UserSelfUpdateSerializer, UserCreateSerializer, UserLimitedSerializer,
    LoginSerializer, ChangePasswordSerializer, SetupOwnerSerializer,
    LanguageSerializer, SkillSerializer,
    AccessKeySerializer, AccessKeyIssueSerializer,
    AccessKeyVerifySerializer, AccessKeyRedeemSerializer,
    TwoFactorConfirmSerializer, TwoFactorDisableSerializer,
    TwoFactorPasswordSerializer, TwoFactorStatusSerializer,
    PushSubscriptionSerializer,
)
from apps.core.views import CompanyScopedViewSet


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
    authentication_classes = []  # публичный эндпоинт: без сессии/CSRF

    def get(self, request):
        """
        Проверяет, существует ли платформенный супер-администратор.

        Возвращает:
            Response с {'setup_required': True/False}
        """
        superadmin_exists = User.objects.filter(role=User.Role.SUPERADMIN).exists()
        return Response({'setup_required': not superadmin_exists})


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
    authentication_classes = []  # публичный эндпоинт: без сессии/CSRF

    def post(self, request):
        """
        Создает владельца системы и возвращает JWT токены.

        Проверяет, что владелец еще не существует, валидирует данные,
        создает пользователя с ролью owner и генерирует JWT токены.

        Возвращает:
            Response с данными пользователя и токенами (201 Created)
            или ошибку 403 если владелец уже существует
        """
        serializer = SetupOwnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                if User.objects.filter(role=User.Role.SUPERADMIN).exists():
                    return Response(
                        {'error': 'Setup is already complete.'},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                user = serializer.save()
        except IntegrityError:
            return Response(
                {'error': 'Setup is already complete.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        fingerprint = request.data.get('fingerprint', '')
        refresh = FingerprintRefreshToken.for_user(user)
        if fingerprint:
            refresh.set_fingerprint(fingerprint)

        write_audit_log(
            action=AuditLog.Action.SETUP_OWNER,
            actor=user,
            target=user,
            request=request,
        )
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
    authentication_classes = []  # публичный эндпоинт: без сессии/CSRF
    throttle_scope = 'login'  # защита от подбора пароля

    def post(self, request):
        """
        Аутентифицирует пользователя и генерирует JWT токены.

        Валидирует username/password, при включённом 2FA дополнительно
        проверяет одноразовый код, создает JWT токены, пишет audit log.

        Возвращает:
            Response с данными пользователя и токенами
        """
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        # Второй фактор проверяется ПОСЛЕ пароля и ДО выдачи токенов: пока код
        # не подтверждён, ни access, ни refresh не существуют, поэтому украсть
        # промежуточный токен невозможно.
        if two_factor.has_two_factor(user):
            code = serializer.validated_data.get('otp_code') or ''
            if not code:
                return Response(
                    {'two_factor_required': True,
                     'detail': 'Требуется код двухэтапного подтверждения.'},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            method = two_factor.verify_code(user, code)
            if method is None:
                write_audit_log(
                    action=AuditLog.Action.TWO_FACTOR_FAILED,
                    actor=user, target=user, request=request,
                )
                return Response(
                    {'two_factor_required': True, 'detail': 'Неверный код подтверждения.'},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            if method == two_factor.VERIFY_RECOVERY:
                write_audit_log(
                    action=AuditLog.Action.TWO_FACTOR_RECOVERY_USED,
                    actor=user, target=user, request=request,
                    metadata={'codes_left': two_factor.recovery_codes_left(user)},
                )

        fingerprint = request.data.get('fingerprint', '')
        refresh = FingerprintRefreshToken.for_user(user)
        if fingerprint:
            refresh.set_fingerprint(fingerprint)

        write_audit_log(
            action=AuditLog.Action.LOGIN,
            actor=user,
            target=user,
            request=request,
        )
        return Response({
            'user': UserSerializer(user).data,
            'tokens': {'refresh': str(refresh), 'access': str(refresh.access_token)},
            'fingerprint_required': bool(fingerprint),
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
        data = serializer.data
        data['vapid_public_key'] = getattr(django_settings, 'VAPID_PUBLIC_KEY', '')
        return Response(data)

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
        # Смена пароля обесценивает все прежние refresh-токены.
        blacklist_all_tokens(request.user)
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

@extend_schema(tags=['Employees'])
class SkillViewSet(CompanyScopedViewSet):
    """
    ViewSet каталога навыков компании (Skill).

    Навыки изолированы по компании: пользователь видит и меняет только навыки
    своей компании. Чтение доступно любому сотруднику компании; создание,
    изменение и удаление — только владельцу или администратору.

    Endpoint: /api/v1/accounts/skills/
    """
    serializer_class = SkillSerializer
    queryset = Skill.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'category']
    ordering_fields = ['name', 'created_at']

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsCompanyMember(), IsOwnerOrAdmin()]
        return [IsCompanyMember()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Skill.objects.none()
        # employees_total -> используется SkillSerializer вместо COUNT на каждый навык.
        return super().get_queryset().annotate(employees_total=Count('employees', distinct=True))

    def perform_create(self, serializer):
        skill = serializer.save(company=self.request.user.company)
        write_audit_log(
            action=AuditLog.Action.CREATE,
            actor=self.request.user,
            target=skill,
            metadata={'name': skill.name},
            request=self.request,
        )

    def perform_update(self, serializer):
        changes = collect_model_changes(serializer.instance, serializer.validated_data)
        skill = serializer.save()
        if changes:
            write_audit_log(
                action=AuditLog.Action.UPDATE,
                actor=self.request.user,
                target=skill,
                changes=changes,
                request=self.request,
            )

    def perform_destroy(self, instance):
        write_audit_log(
            action=AuditLog.Action.DELETE,
            actor=self.request.user,
            target=instance,
            metadata={'name': instance.name},
            request=self.request,
        )
        instance.delete()


@extend_schema(tags=['Access Keys'])
class AccessKeyVerifyView(APIView):
    """
    Проверка Access Key (первый экран входа сотрудника).

    Endpoint: POST /api/v1/accounts/access-key/verify/
    Публичный. Тело: {"access_key": "SKP-...."}.
    Возвращает {valid: bool, employee?: {...}} — не раскрывая пароль/логику.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'access_key_verify'  # защита от перебора кодов

    @extend_schema(request=AccessKeyVerifySerializer, responses=None)
    def post(self, request):
        serializer = AccessKeyVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key = verify_access_key(serializer.validated_data['access_key'])
        if not key:
            return Response({'valid': False})
        return Response({
            'valid': True,
            'employee': {
                'full_name': key.user.full_name or key.user.username,
                'username': key.user.username,
                'company': key.company.name,
                'role': key.user.role,
            },
        })


@extend_schema(tags=['Access Keys'])
class AccessKeyRedeemView(APIView):
    """
    Активация аккаунта сотрудника по Access Key.

    Endpoint: POST /api/v1/accounts/access-key/redeem/
    Публичный. Тело: {"access_key": "SKP-....", "new_password": "..."}.
    При успехе активирует аккаунт, задаёт пароль, помечает ключ использованным
    и возвращает пользователя + JWT-токены (сразу вход).
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'access_key_redeem'  # защита от перебора кодов

    @extend_schema(request=AccessKeyRedeemSerializer, responses=None)
    def post(self, request):
        serializer = AccessKeyRedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, error = redeem_access_key(
            code=serializer.validated_data['access_key'],
            new_password=serializer.validated_data['new_password'],
        )
        if error == 'company_inactive':
            return Response({'detail': 'Company is deactivated'}, status=status.HTTP_400_BAD_REQUEST)
        if error or user is None:
            return Response(
                {'detail': 'Invalid, expired or already used access key'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        fingerprint = request.data.get('fingerprint', '')
        refresh = FingerprintRefreshToken.for_user(user)
        if fingerprint:
            refresh.set_fingerprint(fingerprint)

        write_audit_log(
            action=AuditLog.Action.ACCESS_KEY_REDEEMED,
            actor=user,
            target=user,
            request=request,
        )
        return Response({
            'user': UserSerializer(user).data,
            'tokens': {'refresh': str(refresh), 'access': str(refresh.access_token)},
        })


@extend_schema(tags=['Employees'])
class UserViewSet(CompanyScopedViewSet):
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
    queryset = User.objects.all()  # для интроспекции схемы; runtime-фильтрация ниже
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['username', 'full_name', 'phone', 'position', 'department']
    filterset_fields = ['role', 'is_active', 'status', 'department']
    ordering_fields = ['full_name', 'created_at', 'hire_date']

    def get_queryset(self):
        """
        Возвращает queryset пользователей в зависимости от роли текущего пользователя.

        Логика фильтрации:
        - Owner: видит всех пользователей
        - Admin: видит только работников
        - Worker: не видит никого (пустой queryset)

        Доп. фильтр ?skill=<id> сужает выборку по навыку (в рамках компании).

        Возвращает:
            QuerySet - отфильтрованный список пользователей
        """
        if getattr(self, 'swagger_fake_view', False):
            return User.objects.none()
        user = self.request.user
        # Пользователи всегда ограничены своей компанией.
        if user.is_owner:
            queryset = super().get_queryset()
        elif user.is_admin:
            queryset = super().get_queryset().filter(role='worker')
        else:
            return User.objects.none()

        skill_id = self.request.query_params.get('skill')
        if skill_id:
            # Нечисловое значение раньше доходило до ORM и давало 500.
            queryset = queryset.filter(skills__id=parse_int_param(skill_id, 'skill'))

        # Навыки тянем с аннотацией employees_total, иначе SkillSerializer делал
        # COUNT на каждый навык каждого сотрудника (N+1).
        skills_qs = Skill.objects.annotate(employees_total=Count('employees', distinct=True))
        return (
            queryset.select_related('company')
            .prefetch_related(Prefetch('skills', queryset=skills_qs))
            .distinct()
        )

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
        if getattr(self, 'swagger_fake_view', False) or self.request.user.is_owner:
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
        # Кастомные @action: их permission_classes не применяются автоматически,
        # т.к. get_permissions переопределён — задаём права явно здесь.
        if self.action == 'access_key':
            return [IsOwnerOrAdmin()]
        if self.action in ('toggle_active', 'reset_password'):
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
            # Владелец может создавать admin и worker только в своей компании.
            if requested_role in (User.Role.OWNER, User.Role.SUPERADMIN):
                raise ValidationError({'role': 'Owner can create only admin or worker accounts'})
            created_user = serializer.save(company=user.company)
            write_audit_log(
                action=AuditLog.Action.CREATE,
                actor=user,
                target=created_user,
                metadata={'created_role': created_user.role},
                request=self.request,
            )
            return

        if user.is_admin:
            # Администратор может создавать только workers своей компании.
            if not user.can_create_workers:
                raise PermissionDenied('You do not have permission to create workers')
            if requested_role != User.Role.WORKER:
                raise PermissionDenied('Administrators can create only worker accounts')
            created_user = serializer.save(
                company=user.company,
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

        Только владелец может обновлять пользователей. Изменения скалярных полей
        и назначенных навыков (M2M) записываются в audit log. M2M обрабатывается
        отдельно: collect_model_changes не умеет сравнивать менеджер отношений,
        а DRF применяет M2M только ПОСЛЕ save(), поэтому снимаем старые id до, а
        новые — после сохранения.
        """
        instance = serializer.instance
        old_skill_ids = sorted(instance.skills.values_list('id', flat=True))
        scalar_data = {k: v for k, v in serializer.validated_data.items() if k != 'skills'}
        changes = collect_model_changes(instance, scalar_data)

        updated_user = serializer.save()

        new_skill_ids = sorted(updated_user.skills.values_list('id', flat=True))
        if old_skill_ids != new_skill_ids:
            changes['skills'] = {'old': old_skill_ids, 'new': new_skill_ids}

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
        # Помечаем индивидуальную блокировку, чтобы разблокировка КОМПАНИИ её
        # не сняла молча (blocked_by_owner=True сохраняется через company-каскад).
        user.blocked_by_owner = not user.is_active
        user.save(update_fields=['is_active', 'blocked_by_owner'])
        if not user.is_active:
            # Блокировка — немедленно обрываем активные сессии (refresh-токены).
            blacklist_all_tokens(user)
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
            {"new_password": "string"} (минимум 8 символов)

        Возвращает:
            {'message': 'Password reset successfully'}
        """
        user = self.get_object()
        new_password = request.data.get('new_password')
        if not new_password or len(new_password) < 8:
            return Response({'error': 'Password must be at least 8 characters'}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.save()
        # Принудительный сброс пароля выгоняет все активные сессии сотрудника.
        blacklist_all_tokens(user)
        write_audit_log(
            action=AuditLog.Action.RESET_PASSWORD,
            actor=request.user,
            target=user,
            request=request,
        )
        return Response({'message': 'Password reset successfully'})

    @extend_schema(request=AccessKeyIssueSerializer, responses=AccessKeySerializer)
    @action(detail=True, methods=['get', 'post'], permission_classes=[IsOwnerOrAdmin])
    def access_key(self, request, pk=None):
        """
        Access Key сотрудника.

        GET  — текущий активный ключ (или null).
        POST — выпустить/перевыпустить ключ (прежний активный отзывается).
               Тело: {"expires_in_days": N?}. Возвращает код в поле key.

        Доступно владельцу/администратору только для сотрудников своей компании
        (get_object ограничен company через get_queryset).
        """
        employee = self.get_object()

        if request.method == 'POST':
            if employee.is_owner or employee.is_superadmin:
                raise ValidationError({'detail': 'Cannot issue an access key for this account.'})
            serializer = AccessKeyIssueSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            try:
                key = issue_access_key(
                    user=employee,
                    created_by=request.user,
                    expires_in_days=serializer.validated_data.get('expires_in_days'),
                )
            except ValueError as exc:
                # blocked_by_owner / включённое 2FA и т.п. -> 400, а не 500.
                raise ValidationError({'detail': str(exc)})
            write_audit_log(
                action=AuditLog.Action.ACCESS_KEY_ISSUED,
                actor=request.user,
                target=key,
                metadata={'employee': employee.username},
                request=request,
            )
            return Response(AccessKeySerializer(key).data, status=status.HTTP_201_CREATED)

        key = (
            employee.access_keys.filter(status=AccessKey.Status.ACTIVE)
            .select_related('user').first()
        )
        return Response(AccessKeySerializer(key).data if key else None)


@extend_schema(tags=['Push'])
class PushSubscriptionView(APIView):
    """
    Управление Web Push подпиской.

    POST /api/v1/accounts/push/subscribe/
      Сохраняет push-подписку браузера. Тело:
      {"endpoint": "...", "keys": {"p256dh": "...", "auth": "..."}}

    DELETE /api/v1/accounts/push/unsubscribe/
      Удаляет подписку по endpoint.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        endpoint = request.data.get('endpoint')
        keys = request.data.get('keys', {})
        if not endpoint or not keys.get('p256dh') or not keys.get('auth'):
            return Response(
                {'error': 'endpoint, keys.p256dh and keys.auth are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sub, created = PushSubscription.objects.update_or_create(
            user=request.user,
            endpoint=endpoint,
            defaults={
                'company': request.user.company,
                'p256dh_key': keys['p256dh'],
                'auth_key': keys['auth'],
                'user_agent': request.META.get('HTTP_USER_AGENT', '')[:500],
                'is_active': True,
            },
        )
        return Response(PushSubscriptionSerializer(sub).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def delete(self, request):
        endpoint = request.data.get('endpoint')
        if not endpoint:
            return Response({'error': 'endpoint is required'}, status=status.HTTP_400_BAD_REQUEST)
        deleted, _ = PushSubscription.objects.filter(
            user=request.user, endpoint=endpoint
        ).delete()
        return Response({'deleted': deleted > 0}, status=status.HTTP_200_OK)


class TwoFactorStatusView(APIView):
    """
    Состояние двухэтапного подтверждения текущего пользователя.

    Endpoint: GET /api/v1/accounts/me/2fa/
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=TwoFactorStatusSerializer)
    def get(self, request):
        return Response({
            'enabled': two_factor.has_two_factor(request.user),
            'recovery_codes_left': two_factor.recovery_codes_left(request.user),
        })


class TwoFactorSetupView(APIView):
    """
    Шаг 1 подключения 2FA: выдать секрет и QR-код.

    Endpoint: POST /api/v1/accounts/me/2fa/setup/
    Тело: {"password": "текущий пароль"}

    Пока код не подтверждён (шаг 2), 2FA НЕ включено — сотрудник не может
    случайно заблокировать себе вход, отсканировав QR и закрыв страницу.
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = 'two_factor'

    @extend_schema(request=TwoFactorPasswordSerializer, responses=None)
    def post(self, request):
        serializer = TwoFactorPasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        try:
            device = two_factor.begin_setup(request.user)
        except ValueError:
            raise ValidationError(
                {'detail': 'Двухэтапное подтверждение уже включено. Сначала отключите его.'}
            )
        return Response({
            'secret': device.config_url.split('secret=')[1].split('&')[0],
            'otpauth_uri': two_factor.provisioning_uri(device),
            'qr_code': two_factor.qr_code_data_uri(device),
        })


class TwoFactorConfirmView(APIView):
    """
    Шаг 2 подключения 2FA: подтвердить кодом из приложения.

    Endpoint: POST /api/v1/accounts/me/2fa/confirm/
    Тело: {"code": "123456"}

    Возвращает резервные коды. Они показываются ОДИН раз и в открытом виде
    больше нигде не доступны.
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = 'two_factor'

    @extend_schema(request=TwoFactorConfirmSerializer, responses=None)
    def post(self, request):
        serializer = TwoFactorConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        codes = two_factor.confirm_setup(request.user, serializer.validated_data['code'])
        if codes is None:
            write_audit_log(
                action=AuditLog.Action.TWO_FACTOR_FAILED,
                actor=request.user, target=request.user, request=request,
            )
            raise ValidationError({'code': 'Неверный код подтверждения.'})

        write_audit_log(
            action=AuditLog.Action.TWO_FACTOR_ENABLED,
            actor=request.user, target=request.user, request=request,
        )
        return Response({'enabled': True, 'recovery_codes': codes})


class TwoFactorDisableView(APIView):
    """
    Отключение 2FA.

    Endpoint: POST /api/v1/accounts/me/2fa/disable/
    Тело: {"password": "...", "code": "123456"}

    Требуются оба фактора: знание пароля не должно позволять снять защиту.
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = 'two_factor'

    @extend_schema(request=TwoFactorDisableSerializer, responses=None)
    def post(self, request):
        serializer = TwoFactorDisableSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        if not two_factor.has_two_factor(request.user):
            raise ValidationError({'detail': 'Двухэтапное подтверждение не включено.'})
        if two_factor.verify_code(request.user, serializer.validated_data['code']) is None:
            write_audit_log(
                action=AuditLog.Action.TWO_FACTOR_FAILED,
                actor=request.user, target=request.user, request=request,
            )
            raise ValidationError({'code': 'Неверный код подтверждения.'})

        two_factor.disable(request.user)
        write_audit_log(
            action=AuditLog.Action.TWO_FACTOR_DISABLED,
            actor=request.user, target=request.user, request=request,
        )
        return Response({'enabled': False})


class TwoFactorRecoveryCodesView(APIView):
    """
    Перевыпуск резервных кодов.

    Endpoint: POST /api/v1/accounts/me/2fa/recovery-codes/
    Тело: {"password": "текущий пароль"}

    Старые коды перестают действовать сразу — если сотрудник потерял список,
    найденная копия уже бесполезна.
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = 'two_factor'

    @extend_schema(request=TwoFactorPasswordSerializer, responses=None)
    def post(self, request):
        serializer = TwoFactorPasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        if not two_factor.has_two_factor(request.user):
            raise ValidationError({'detail': 'Двухэтапное подтверждение не включено.'})

        codes = two_factor.regenerate_recovery_codes(request.user)
        write_audit_log(
            action=AuditLog.Action.TWO_FACTOR_RECOVERY_REGENERATED,
            actor=request.user, target=request.user, request=request,
        )
        return Response({'recovery_codes': codes})
