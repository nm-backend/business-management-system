"""
Serializers for User model and authentication.

Этот модуль содержит сериализаторы Django REST Framework для модели User
и операций аутентификации. Разные сериализаторы используются для разных
ролей и сценариев для контроля доступа к чувствительным данным.

ВАЖНО: Финансовые и административные поля исключаются для non-owner пользователей.
"""
from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import User


class UserSerializer(serializers.ModelSerializer):
    """
    Полный сериализатор пользователя (только для owner).

    Включает все поля пользователя, включая административные права.
    Используется только для владельца, который имеет полный доступ
    ко всей информации о пользователях.

    Поля:
        Все поля модели User + display_role (вычисляемое поле)

    Права доступа:
        Только owner может видеть полный список пользователей
    """
    display_role = serializers.ReadOnlyField()
    is_owner = serializers.ReadOnlyField()
    is_admin = serializers.ReadOnlyField()
    is_worker = serializers.ReadOnlyField()
    is_superadmin = serializers.ReadOnlyField()
    company_name = serializers.CharField(source='company.name', read_only=True, default=None)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'full_name', 'phone', 'email',
            'role', 'display_role', 'is_owner', 'is_admin', 'is_worker', 'is_superadmin',
            'company', 'company_name', 'avatar', 'language',
            'is_active', 'can_write_to_owner', 'can_create_workers',
            'can_see_other_workers', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'role', 'company', 'created_at', 'updated_at', 'display_role',
        ]


class UserSelfUpdateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для самостоятельного обновления профиля.

    Пользователь может редактировать только свои личные данные,
    не включая роль и административные права.

    Поля:
        full_name, phone, email, avatar, language

    Используется:
        - В MeView для PATCH /api/v1/accounts/me/
    """
    class Meta:
        model = User
        fields = ['full_name', 'phone', 'email', 'avatar', 'language']


class UserCreateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для создания новых пользователей.

    Используется администраторами и владельцем для создания
    новых аккаунтов. Пароль передается отдельно и хешируется.

    Поля:
        username, password, full_name, phone, email, role, language,
        can_write_to_owner, can_create_workers, can_see_other_workers

    Валидация:
        - password: минимальная длина 8 символов
        - Пароль хешируется перед сохранением

    Безопасность:
        - Поле password помечено как write_only (не возвращается в API)
    """
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = [
            'username', 'password', 'full_name', 'phone', 'email',
            'role', 'language', 'can_write_to_owner',
            'can_create_workers', 'can_see_other_workers',
        ]

    def validate(self, attrs):
        candidate = User(
            username=attrs.get('username', ''),
            full_name=attrs.get('full_name', ''),
        )
        try:
            validate_password(attrs['password'], candidate)
        except DjangoValidationError as error:
            raise serializers.ValidationError({'password': error.messages}) from error
        return attrs

    def create(self, validated_data):
        """
        Создает пользователя с хешированием пароля.

        Аргументы:
            validated_data: dict - валидированные данные из запроса

        Возвращает:
            User - созданный пользователь с хешированным паролем
        """
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UserLimitedSerializer(serializers.ModelSerializer):
    """
    Ограниченный сериализатор пользователя (для admin).

    Исключает чувствительные административные поля.
    Администраторы могут видеть базовую информацию о пользователях,
    но не их права и настройки.

    Поля:
        id, username, full_name, phone, role, display_role, avatar, is_active

    Исключены:
        - can_write_to_owner, can_create_workers, can_see_other_workers
        - email, language, created_at, updated_at

    Используется:
        - В UserViewSet для admin роли
    """
    display_role = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'full_name', 'phone',
            'role', 'display_role', 'avatar', 'is_active',
        ]

class LoginSerializer(serializers.Serializer):
    """
    Сериализатор для аутентификации пользователя.

    Проверяет username и password, возвращает аутентифицированного пользователя.

    Поля:
        username: CharField - имя пользователя
        password: CharField - пароль

    Валидация:
        - Проверяет существование пользователя
        - Проверяет правильность пароля
        - Проверяет активность аккаунта (is_active)

    Используется:
        - В LoginView для POST /api/v1/accounts/login/
    """
    username = serializers.CharField()
    password = serializers.CharField()

    def validate(self, data):
        """
        Валидирует учетные данные и аутентифицирует пользователя.

        Аргументы:
            data: dict - данные с username и password

        Возвращает:
            dict - валидированные данные с добавленным объектом user

        Исключения:
            ValidationError - если username/password неверны или аккаунт деактивирован
        """
        user = authenticate(
            username=data['username'],
            password=data['password']
        )
        if user is None:
            raise serializers.ValidationError('Invalid username or password')
        if not user.is_active:
            raise serializers.ValidationError('Account is deactivated')
        # Пользователь заблокированной компании не может войти.
        if user.company_id is not None and not user.company.is_active:
            raise serializers.ValidationError('Company is deactivated')
        data['user'] = user
        return data


class ChangePasswordSerializer(serializers.Serializer):
    """
    Сериализатор для изменения пароля пользователя.

    Позволяет пользователю изменить свой пароль после проверки текущего.

    Поля:
        old_password: CharField - текущий пароль для проверки
        new_password: CharField - новый пароль (минимум 8 символов)

    Валидация:
        - old_password должен совпадать с текущим паролем
        - new_password: минимальная длина 8 символов

    Используется:
        - В ChangePasswordView для POST /api/v1/accounts/me/password/
    """
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)

    def validate_old_password(self, value):
        """
        Проверяет, что old_password совпадает с текущим паролем пользователя.

        Аргументы:
            value: str - текущий пароль из запроса

        Возвращает:
            str - валидированный пароль

        Исключения:
            ValidationError - если пароль неверный
        """
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect')
        return value

    def validate(self, attrs):
        user = self.context['request'].user
        try:
            validate_password(attrs['new_password'], user)
        except DjangoValidationError as error:
            raise serializers.ValidationError({'new_password': error.messages}) from error
        return attrs


class SetupOwnerSerializer(serializers.Serializer):
    """
    Сериализатор для начальной настройки системы (создание владельца).

    Используется только при первом запуске системы для создания
    аккаунта владельца. После создания владельца этот endpoint
    становится недоступным.

    Поля:
        username: CharField - имя пользователя (3-150 символов)
        password: CharField - пароль (минимум 8 символов, write_only)
        password_confirm: CharField - подтверждение пароля (write_only)
        full_name: CharField - полное имя
        phone: CharField - телефон (опционально)

    Валидация:
        - password и password_confirm должны совпадать
        - username должен быть уникальным

    Особенности:
        - Автоматически устанавливает role='owner'
        - Устанавливает is_staff=True и is_superuser=True
        - Пароль хешируется перед сохранением

    Используется:
        - В SetupOwnerView для POST /api/v1/accounts/setup/owner/
    """
    username = serializers.CharField(min_length=3, max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)
    full_name = serializers.CharField(max_length=255)
    phone = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        default='',
    )

    def validate(self, data):
        """
        Валидирует данные для создания владельца.

        Проверяет совпадение паролей и уникальность username.

        Аргументы:
            data: dict - данные из запроса

        Возвращает:
            dict - валидированные данные

        Исключения:
            ValidationError - если пароли не совпадают или username занят
        """
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match'})
        if User.objects.filter(username=data['username']).exists():
            raise serializers.ValidationError({'username': 'Username already exists'})
        candidate = User(
            username=data['username'],
            full_name=data['full_name'],
        )
        try:
            validate_password(data['password'], candidate)
        except DjangoValidationError as error:
            raise serializers.ValidationError({'password': error.messages}) from error
        return data

    def create(self, validated_data):
        """
        Создает пользователя с ролью владельца.

        Аргументы:
            validated_data: dict - валидированные данные

        Возвращает:
            User - созданный владелец с хешированным паролем
        """
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        # Первый пользователь системы - платформенный супер-администратор:
        # он создаёт компании и их владельцев, но сам к компании не привязан.
        user = User(
            username=validated_data['username'],
            full_name=validated_data.get('full_name', ''),
            phone=validated_data.get('phone', ''),
            role=User.Role.SUPERADMIN,
            company=None,
            is_staff=True,
            is_superuser=True,
        )
        user.set_password(password)
        user.save()
        return user


class LanguageSerializer(serializers.Serializer):
    """
    Сериализатор для изменения языка интерфейса.

    Позволяет пользователю выбрать предпочитаемый язык (узбекский или русский).

    Поля:
        language: ChoiceField - код языка (uz_cyrl или ru)

    Валидация:
        - language должен быть одним из User.Language.choices

    Используется:
        - В ChangeLanguageView для POST /api/v1/accounts/me/language/
    """
    language = serializers.ChoiceField(choices=User.Language.choices)
