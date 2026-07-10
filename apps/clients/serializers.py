"""
Serializers for clients API.

Этот модуль содержит сериализаторы для модели Client с защитой
финансовых данных для non-owner пользователей.
"""
from rest_framework import serializers
from .models import Client


class ClientSerializer(serializers.ModelSerializer):
    """
    Сериализатор клиента с финансовыми данными.

    Используется только для владельца (owner).
    Включает все поля включая финансовые.
    """
    class Meta:
        model = Client
        fields = [
            'id', 'name', 'phone', 'address',
            'total_orders_amount', 'total_paid', 'debt', 'profit',
            'is_active', 'is_archived', 'notes',
            'has_debt', 'has_active_orders',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class ClientLimitedSerializer(serializers.ModelSerializer):
    """
    Сериализатор клиента без финансовых данных.

    Используется для администраторов и работников.
    Исключает финансовые поля (суммы, долги, прибыль).
    """
    class Meta:
        model = Client
        fields = [
            'id', 'name', 'phone', 'address',
            'is_active', 'is_archived', 'notes',
            'has_active_orders',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class ClientCreateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для создания клиента.

    Используется при создании нового клиента.
    Финансовые поля инициализируются нулями.
    """
    class Meta:
        model = Client
        fields = [
            'name', 'phone', 'address', 'notes'
        ]

    def create(self, validated_data):
        return Client.objects.create(
            **validated_data,
            total_orders_amount=0,
            total_paid=0,
            debt=0,
            profit=0,
            is_active=True,
            is_archived=False
        )
