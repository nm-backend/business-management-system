"""
Сериализаторы компаний (для платформенного супер-администратора).

Создание компании атомарно создаёт её владельца (owner). Владелец далее сам
управляет своей компанией: складом, заказами, работниками и т.д.
"""
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import User
from .models import Company


class CompanySerializer(serializers.ModelSerializer):
    """Компания с краткой сводкой по владельцу и числу пользователей."""
    owner_username = serializers.SerializerMethodField()
    owner_full_name = serializers.SerializerMethodField()
    # Значение приходит из annotate(users_count=Count('users')) в CompanyViewSet.
    users_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Company
        fields = [
            'id', 'name', 'is_active', 'owner_username', 'owner_full_name',
            'users_count', 'created_at', 'updated_at',
        ]
        # is_active меняется ТОЛЬКО через действие toggle_active (он деактивирует
        # сотрудников и пишет audit). Прямой PATCH is_active обходил каскад:
        # компания «блокировалась», а её refresh-токены продолжали работать.
        read_only_fields = ['is_active', 'created_at', 'updated_at']

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
        return company
