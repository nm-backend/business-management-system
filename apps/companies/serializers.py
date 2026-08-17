"""
Сериализаторы компаний (для платформенного супер-администратора).

Создание компании атомарно создаёт её владельца (owner) и выдаёт триал-подписку
на DEFAULT_SUBSCRIPTION_DAYS дней. Владелец далее сам управляет своей компанией:
складом, заказами, работниками и т.д.

Подписку видит и меняет ТОЛЬКО супер-администратор: обычные поля сериализатора
только читаются, все изменения идут через отдельные action'ы
(activate/extend/set_end/freeze/unfreeze) с записью истории и аудита.
"""
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import User
from apps.billing.serializers import SubscriptionSummarySerializer
from .models import Company
from .subscriptions import activate_for_new_company


class CompanySerializer(serializers.ModelSerializer):
    """
    Компания с краткой сводкой: владелец, счётчики, состояние подписки.

    Счётчики (users/clients/orders) и последняя активность приходят из
    annotate() в CompanyViewSet — без отдельных COUNT на каждую компанию.
    Финансовые данные компаний супер-администратор НЕ получает: здесь только
    операционные счётчики и статус подписки (управление платформой, а не
    просмотр чужой бухгалтерии).
    """
    owner_username = serializers.SerializerMethodField()
    owner_full_name = serializers.SerializerMethodField()
    # Значение приходит из annotate(users_count=Count('users')) в CompanyViewSet.
    users_count = serializers.IntegerField(read_only=True)
    clients_count = serializers.IntegerField(read_only=True)
    orders_count = serializers.IntegerField(read_only=True)
    last_activity = serializers.DateTimeField(read_only=True, allow_null=True)
    # Флаг «есть непрочитанный запрос на продление» (аннотация в CompanyViewSet).
    has_renewal_request = serializers.BooleanField(read_only=True, default=False)
    subscription_status = serializers.SerializerMethodField()
    subscription_status_display = serializers.SerializerMethodField()
    # Явно read-only: план меняется ТОЛЬКО через subscription_change_plan
    # (история + аудит + уведомления), прямой PATCH plan_id был бы
    # mass-assignment в обход бизнес-логики.
    plan_id = serializers.IntegerField(read_only=True)
    plan_name = serializers.SerializerMethodField()
    days_left = serializers.SerializerMethodField()
    grace_end = serializers.SerializerMethodField()
    logo_url = serializers.SerializerMethodField()
    # Сводка подписки (select_related('subscription') в CompanyViewSet).
    subscription = SubscriptionSummarySerializer(read_only=True)

    class Meta:
        model = Company
        fields = [
            'id', 'name', 'logo', 'logo_url', 'is_active',
            'owner_username', 'owner_full_name',
            'users_count', 'clients_count', 'orders_count',
            'plan_id', 'plan_name', 'is_trial', 'grace_period_days',
            'subscription_status', 'subscription_status_display',
            'subscription_start', 'subscription_end',
            'days_left', 'grace_end',
            'last_activity', 'has_renewal_request', 'subscription',
            'created_at', 'updated_at',
        ]
        # is_active меняется ТОЛЬКО через действие toggle_active (он деактивирует
        # сотрудников и пишет audit). Прямой PATCH is_active обходил каскад:
        # компания «блокировалась», а её refresh-токены продолжали работать.
        # Поля подписки (включая план и флаг триала) — ТОЛЬКО через subscription
        # action'ы (история + аудит).
        read_only_fields = [
            'is_active', 'logo', 'logo_url', 'created_at', 'updated_at',
            'plan', 'is_trial', 'grace_period_days',
            'subscription_status', 'subscription_start', 'subscription_end',
            'last_activity',
        ]

    def _owner(self, obj):
        # CompanyViewSet префетчит владельцев в obj._owner_list (без доп. запросов).
        # Фоллбэк на запрос — для контекстов без префетча (retrieve по прямому qs).
        owners = getattr(obj, '_owner_list', None)
        if owners is not None:
            return owners[0] if owners else None
        return obj.users.filter(role=User.Role.OWNER).first()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_owner_username(self, obj):
        owner = self._owner(obj)
        return owner.username if owner else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_owner_full_name(self, obj):
        owner = self._owner(obj)
        return owner.full_name if owner else None

    @extend_schema_field(serializers.CharField())
    def get_subscription_status(self, obj):
        # Фактический статус: формальный 'active' может уже быть просроченным
        # (Celery ещё не отработал) — отдаём effective.
        return obj.effective_subscription_status

    @extend_schema_field(serializers.CharField())
    def get_subscription_status_display(self, obj):
        return dict(Company.SubscriptionStatus.choices).get(
            obj.effective_subscription_status, obj.subscription_status,
        )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_plan_name(self, obj):
        plan = getattr(obj, 'plan', None)
        return plan.name if plan else None

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_days_left(self, obj):
        return obj.subscription_days_left

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_grace_end(self, obj):
        grace_end = obj.grace_end
        return grace_end.isoformat() if grace_end else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_logo_url(self, obj):
        if not obj.logo:
            return None
        try:
            return obj.logo.url
        except Exception:
            return None


class CompanyCreateSerializer(serializers.ModelSerializer):
    """Создание компании вместе с её владельцем (одной транзакцией)."""
    owner_username = serializers.CharField(write_only=True, min_length=3, max_length=150)
    owner_password = serializers.CharField(write_only=True, min_length=8)
    owner_full_name = serializers.CharField(write_only=True, required=False, allow_blank=True, default='')
    owner_phone = serializers.CharField(write_only=True, required=False, allow_blank=True, default='')

    class Meta:
        model = Company
        fields = ['id', 'name', 'owner_username', 'owner_password', 'owner_full_name', 'owner_phone']

    def validate_owner_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('Username already exists')
        return value

    def validate_owner_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as error:
            raise serializers.ValidationError(list(error.messages)) from error
        return value

    @transaction.atomic
    def create(self, validated_data):
        owner_username = validated_data.pop('owner_username')
        owner_password = validated_data.pop('owner_password')
        owner_full_name = validated_data.pop('owner_full_name', '')
        owner_phone = validated_data.pop('owner_phone', '')

        company = Company.objects.create(**validated_data)
        owner = User(
            username=owner_username,
            full_name=owner_full_name,
            phone=owner_phone,
            role=User.Role.OWNER,
            company=company,
        )
        owner.set_password(owner_password)
        owner.save()
        # SaaS: новая компания сразу получает триал-подписку (30 дней).
        activate_for_new_company(company)
        return company
