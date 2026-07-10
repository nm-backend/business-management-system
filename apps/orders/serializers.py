"""
Serializers for orders API.

Этот модуль содержит сериализаторы для модели Order с защитой
финансовых данных для non-owner пользователей.
"""
from decimal import Decimal

from rest_framework import serializers
from .models import Order, OrderStatus, PaymentStatus


class PaymentUpdateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        min_value=Decimal('0.01'),
    )


class OrderSerializer(serializers.ModelSerializer):
    """
    Сериализатор заказа с финансовыми данными.

    Используется только для владельца (owner).
    Включает все поля включая финансовые суммы.
    """
    client_name = serializers.CharField(source='client.name', read_only=True)
    product_name = serializers.CharField(read_only=True)
    worker_name = serializers.CharField(source='worker.username', read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'client', 'client_name', 'product', 'product_name',
            'quantity', 'unit', 'deadline', 'material', 'worker', 'worker_name',
            'comment', 'drawing', 'status', 'payment_status',
            'total_amount', 'paid_amount',
            'material_shortage', 'is_overdue',
            'is_paid', 'has_debt',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class OrderLimitedSerializer(serializers.ModelSerializer):
    """
    Сериализатор заказа без финансовых данных.

    Используется для администраторов и работников.
    Исключает финансовые поля (суммы).
    """
    client_name = serializers.CharField(source='client.name', read_only=True)
    product_name = serializers.CharField(read_only=True)
    worker_name = serializers.CharField(source='worker.username', read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'client', 'client_name', 'product', 'product_name',
            'quantity', 'unit', 'deadline', 'material', 'worker', 'worker_name',
            'comment', 'drawing', 'status', 'payment_status',
            'material_shortage', 'is_overdue',
            'is_paid', 'has_debt',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class OrderCreateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для создания заказа.

    Используется при создании нового заказа.
    """
    class Meta:
        model = Order
        fields = [
            'client', 'product', 'product_name',
            'quantity', 'unit', 'deadline', 'material',
            'comment', 'drawing'
        ]

    def create(self, validated_data):
        return Order.objects.create(
            **validated_data,
            status=OrderStatus.NEW,
            payment_status=PaymentStatus.UNPAID,
            total_amount=0,
            paid_amount=0,
            material_shortage=False,
            is_overdue=False
        )
