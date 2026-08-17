"""
Serializers for User model and authentication.

Этот модуль содержит сериализаторы Django REST Framework для модели User
и операций аутентификации. Разные сериализаторы используются для разных
ролей и сценариев для контроля доступа к чувствительным данным.

ВАЖНО: Финансовые и административные поля исключаются для non-owner пользователей.
"""
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from apps.core.validators import validate_image_upload

from .models import AccessKey, PushSubscription, Skill, User


class SkillSerializer(serializers.ModelSerializer):
    """
    Сериализатор навыка (каталог навыков компании).

    company проставляется сервером (из request.user.company) и клиентом не
    задаётся — это защищает изоляцию арендаторов.
    """
    # Раньше было source='employees.count' -> отдельный COUNT на КАЖДЫЙ навык
    # (в т.ч. вложенный в каждого сотрудника) = N+1. Теперь берём аннотацию
    # queryset'а, а если её нет — считаем как раньше. Формат ответа не изменился.
    employee_count = serializers.SerializerMethodField()

    class Meta:
        model = Skill
        fields = ['id', 'name', 'category', 'employee_count', 'created_at']
        read_only_fields = ['id', 'employee_count', 'created_at']

    def get_employee_count(self, obj):
        annotated = getattr(obj, 'employees_total', None)
        return annotated if annotated is not None else obj.employees.count()

    def validate_name(self, value):
        # Дубликат (company, name) ронял создание в IntegrityError — 500 вместо 400.
        request = self.context.get('request')
        company_id = getattr(request.user, 'company_id', None) if request else None
        instance = getattr(self, 'instance', None)
        duplicate = Skill.objects.filter(name=value)
        if company_id:
            duplicate = duplicate.filter(company_id=company_id)
        if instance is not None:
            duplicate = duplicate.exclude(pk=instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError('Навык с таким названием уже существует.')
        return value


class CompanyScopedSkillsMixin:
    """
    Ограничивает queryset поля skill_ids навыками компании текущего пользователя.

    Так подделанный/чужой id навыка отклоняется валидацией (400) ещё до бизнес-
    логики. View дополнительно перепроверяет принадлежность компании.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        field = self.fields.get('skill_ids')
        if request is not None and field is not None and getattr(request.user, 'company_id', None):
            field.child_relation.queryset = Skill.objects.filter(company_id=request.user.company_id)


class UserSerializer(CompanyScopedSkillsMixin, serializers.ModelSerializer):
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
    is_manager = serializers.ReadOnlyField()
    is_superadmin = serializers.ReadOnlyField()
    company_name = serializers.CharField(source='company.name', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    skills = SkillSerializer(many=True, read_only=True)
    skill_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, required=False, source='skills',
        queryset=Skill.objects.all(),  # сужается по компании в CompanyScopedSkillsMixin
    )
    avatar = serializers.ImageField(required=False, allow_null=True, validators=[validate_image_upload])
    # SaaS: статус подписки компании — SPA по нему решает, показывать ли
    # рабочее приложение или экран «Подписка истекла». У супер-админа None.
    subscription_status = serializers.SerializerMethodField()
    subscription_status_display = serializers.SerializerMethodField()
    subscription_end = serializers.SerializerMethodField()
    subscription_grace_end = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'full_name', 'phone', 'email',
            'role', 'display_role', 'is_owner', 'is_admin', 'is_worker', 'is_manager', 'is_superadmin',
            'company', 'company_name', 'avatar', 'language',
            'position', 'department', 'birth_date', 'hire_date', 'bio',
            'status', 'status_display', 'last_activity',
            'skills', 'skill_ids',
            'is_active', 'can_write_to_owner', 'can_create_workers',
            'can_see_other_workers', 'created_at', 'updated_at',
            'subscription_status', 'subscription_status_display', 'subscription_end',
            'subscription_grace_end',
        ]
        read_only_fields = [
            'id', 'role', 'company', 'created_at', 'updated_at', 'display_role',
            'last_activity',
            # is_active меняется ТОЛЬКО через action toggle_active (с проверкой
            # «нельзя деактивировать владельца» и блэклистом токенов), а не
            # обычным PATCH /users/{id}/.
            'is_active',
        ]

    def _company(self, obj):
        # user.company подгружается select_related('company') в JWT-аутентификации.
        return getattr(obj, 'company', None)

    def get_subscription_status(self, obj):
        company = self._company(obj)
        if company is None:
            return None
        return company.effective_subscription_status

    def get_subscription_status_display(self, obj):
        company = self._company(obj)
        if company is None:
            return None
        from apps.companies.models import Company as CompanyModel
        return dict(CompanyModel.SubscriptionStatus.choices).get(
            company.effective_subscription_status, company.subscription_status,
        )

    def get_subscription_end(self, obj):
        company = self._company(obj)
        if company is None or company.subscription_end is None:
            return None
        return company.subscription_end.isoformat()

    def get_subscription_grace_end(self, obj):
        """Дата окончания льготного периода (для баннера grace в SPA)."""
        company = self._company(obj)
        if company is None:
            return None
        grace_end = company.grace_end
        return grace_end.isoformat() if grace_end else None


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
    avatar = serializers.ImageField(required=False, allow_null=True, validators=[validate_image_upload])

    class Meta:
        model = User
        # Личные поля профиля. Должность/отдел/дата найма/статус — HR-данные,
        # их задаёт владелец/админ, поэтому сюда НЕ входят.
        fields = ['full_name', 'phone', 'email', 'avatar', 'language', 'bio', 'birth_date']


class UserCreateSerializer(CompanyScopedSkillsMixin, serializers.ModelSerializer):
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
    # Пароль необязателен: если не указан, сотрудник создаётся «приглашённым»
    # (без рабочего пароля) и активирует аккаунт через Access Key.
    password = serializers.CharField(write_only=True, min_length=8, required=False, allow_blank=True)
    skill_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, required=False, source='skills',
        queryset=Skill.objects.all(),  # сужается по компании в CompanyScopedSkillsMixin
    )

    class Meta:
        model = User
        fields = [
            'id', 'username', 'password', 'full_name', 'phone', 'email',
            'role', 'language', 'can_write_to_owner',
            'can_create_workers', 'can_see_other_workers',
            'position', 'department', 'birth_date', 'hire_date', 'bio', 'status',
            'skill_ids',
        ]

    def validate(self, attrs):
        password = attrs.get('password')
        if password:
            candidate = User(
                username=attrs.get('username', ''),
                full_name=attrs.get('full_name', ''),
            )
            try:
                validate_password(password, candidate)
            except DjangoValidationError as error:
                raise serializers.ValidationError({'password': error.messages}) from error
        return attrs

    def validate_username(self, value):
        # Без проверки дубликат username ронял создание в IntegrityError — 500
        # вместо понятного 400 (журнал аудита ждал бы уже созданного юзера).
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('Пользователь с таким логином уже существует.')
        return value

    def create(self, validated_data):
        """
        Создаёт пользователя.

        С паролем — обычный аккаунт. Без пароля — «приглашённый» сотрудник
        с непригодным паролем: он войдёт, только активировав аккаунт через
        Access Key (см. apps.accounts.access_keys).
        """
        password = validated_data.pop('password', None)
        skills = validated_data.pop('skills', None)  # M2M нельзя задать в конструкторе
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        if skills is not None:
            user.skills.set(skills)
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
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    skills = SkillSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'full_name', 'phone',
            'role', 'display_role', 'avatar', 'is_active',
            'position', 'department', 'status', 'status_display', 'skills',
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
    # Второй фактор. Необязателен: у сотрудников без 2FA формат запроса и
    # ответа не меняется. Проверяется в LoginView после пароля.
    otp_code = serializers.CharField(required=False, allow_blank=True)

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
        # authenticate() не возвращает НЕАКТИВНЫХ пользователей вообще
        # (ModelBackend.user_can_authenticate), поэтому проверки is_active и
        # компании ниже были мёртвым кодом: заблокированный аккаунт и аккаунт
        # заблокированной компании отвечали одинаковым «Invalid username or
        # password», и сотрудник не понимал, что его заблокировали. Ищем
        # пользователя сами и проверяем статусы ДО проверки пароля.
        user = User.objects.filter(username=data['username']).first()
        if user is None:
            raise serializers.ValidationError('Неверное имя пользователя или пароль')
        # Сначала компания: при блокировке компании её сотрудники получают
        # is_active=False каскадом, и оба сообщения формально верны, но
        # «Company is deactivated» объясняет причину лучше.
        if user.company_id is not None and not user.company.is_active:
            raise serializers.ValidationError('Компания деактивирована')
        if not user.is_active:
            raise serializers.ValidationError('Аккаунт деактивирован')
        if not user.check_password(data['password']):
            raise serializers.ValidationError('Неверное имя пользователя или пароль')
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


class AccessKeySerializer(serializers.ModelSerializer):
    """Access Key сотрудника (для владельца/админа и супер-админа)."""
    employee = serializers.SerializerMethodField()
    effective_status = serializers.ReadOnlyField()

    class Meta:
        model = AccessKey
        fields = [
            'id', 'key', 'status', 'effective_status', 'employee',
            'expires_at', 'used_at', 'created_at',
        ]
        read_only_fields = fields

    def get_employee(self, obj):
        return {
            'id': obj.user_id,
            'username': obj.user.username,
            'full_name': obj.user.full_name,
            'role': obj.user.role,
        }


class AccessKeyIssueSerializer(serializers.Serializer):
    """Вход для выпуска ключа: необязательный срок действия в днях."""
    expires_in_days = serializers.IntegerField(required=False, min_value=1, max_value=365)


class AccessKeyVerifySerializer(serializers.Serializer):
    """Проверка кода (первый экран входа сотрудника)."""
    access_key = serializers.CharField()


class AccessKeyRedeemSerializer(serializers.Serializer):
    """Активация аккаунта по коду: код + новый пароль."""
    access_key = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as error:
            raise serializers.ValidationError(list(error.messages)) from error
        return value


class TwoFactorPasswordSerializer(serializers.Serializer):
    """
    Подтверждение паролем для операций с 2FA.

    Повторный ввод пароля нужен там, где меняется сам второй фактор
    (подключение, перевыпуск резервных кодов): угнанная сессия не должна
    позволять перепривязать 2FA на устройство злоумышленника.
    """
    password = serializers.CharField(required=True, write_only=True)

    def validate_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Пароль неверный.')
        return value


class TwoFactorConfirmSerializer(serializers.Serializer):
    """Подтверждение подключения 2FA кодом из приложения-аутентификатора."""
    code = serializers.CharField(required=True, write_only=True)


class TwoFactorDisableSerializer(TwoFactorPasswordSerializer):
    """
    Отключение 2FA: пароль И действующий код.

    Только пароля недостаточно — иначе тот, кто узнал пароль, снял бы
    второй фактор и обошёл всю защиту. Код можно ввести резервный.
    """
    code = serializers.CharField(required=True, write_only=True)


class TwoFactorStatusSerializer(serializers.Serializer):
    """Состояние 2FA у текущего пользователя (только чтение)."""
    enabled = serializers.BooleanField(read_only=True)
    recovery_codes_left = serializers.IntegerField(read_only=True)


class PushSubscriptionSerializer(serializers.ModelSerializer):
    """Сериализатор для подписки на Web Push уведомления."""

    class Meta:
        model = PushSubscription
        fields = ['id', 'endpoint', 'p256dh_key', 'auth_key', 'user_agent', 'is_active', 'created_at']
        read_only_fields = ['id', 'is_active', 'created_at', 'user_agent']
