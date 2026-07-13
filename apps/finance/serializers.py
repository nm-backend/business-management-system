"""
Serializers for finance API.

Этот модуль содержит сериализаторы для финансовых моделей.
Все финансовые данные доступны только владельцу (owner).
"""
from rest_framework import serializers
from .models import Expense, LaborRate, WorkerPayment


class ExpenseSerializer(serializers.ModelSerializer):
    """
    Сериализатор расхода.

    Доступен только владельцу (owner).
    """
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Expense
        fields = [
            'id', 'category', 'amount', 'date', 'comment',
            'receipt_photo', 'created_by', 'created_by_name',
            'payment_method', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'created_by']


class ExpenseCreateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для создания расхода.

    Используется при добавлении нового расхода.
    """
    class Meta:
        model = Expense
        fields = [
            'category', 'amount', 'date', 'comment',
            'receipt_photo', 'payment_method'
        ]
    # created_by и company проставляет ViewSet.perform_create.


class LaborRateSerializer(serializers.ModelSerializer):
    """
    Сериализатор ставки оплаты труда.

    Доступен только владельцу (owner).
    """
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = LaborRate
        fields = [
            'id', 'product', 'product_name', 'operation',
            'rate_per_unit', 'unit', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class LaborRateCreateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для создания ставки оплаты труда.

    Используется при установке ставок оплаты.
    """
    class Meta:
        model = LaborRate
        fields = [
            'product', 'operation', 'rate_per_unit', 'unit'
        ]


class WorkerPaymentSerializer(serializers.ModelSerializer):
    """
    Сериализатор выплаты работнику.

    Доступен только владельцу (owner).
    """
    worker_name = serializers.CharField(source='worker.username', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = WorkerPayment
        fields = [
            'id', 'worker', 'worker_name', 'amount', 'payment_date',
            'payment_type', 'comment', 'created_by', 'created_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'created_by']


class WorkerPaymentCreateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для создания выплаты работнику.

    Используется при выплате зарплаты/аванса.
    """
    class Meta:
        model = WorkerPayment
        fields = [
            'worker', 'amount', 'payment_date', 'payment_type', 'comment'
        ]
    # created_by и company проставляет ViewSet.perform_create.
