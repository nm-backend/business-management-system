"""
Serializers for production API.

Этот модуль содержит сериализаторы для моделей Task и WorkRecord
с защитой финансовых данных для non-owner пользователей.
"""
from rest_framework import serializers
from .models import Task, WorkRecord, TaskStatus, RefusalReason


class TaskSerializer(serializers.ModelSerializer):
    """
    Сериализатор задачи.

    Используется для всех ролей.
    Финансовых полей нет.
    """
    order_id = serializers.IntegerField(source='order.id', read_only=True)
    worker_name = serializers.CharField(source='worker.username', read_only=True)
    assigned_by_name = serializers.CharField(source='assigned_by.username', read_only=True)
    confirmed_by_name = serializers.CharField(source='confirmed_by.username', read_only=True)

    class Meta:
        model = Task
        fields = [
            'id', 'order', 'order_id', 'worker', 'worker_name',
            'assigned_by', 'assigned_by_name', 'status',
            'refusal_reason', 'refusal_comment',
            'assigned_at', 'accepted_at', 'completed_at',
            'confirmed_at', 'confirmed_by', 'confirmed_by_name',
            'rejection_comment', 'is_self_assigned'
        ]
        read_only_fields = ['assigned_at', 'accepted_at', 'completed_at', 'confirmed_at']


class TaskCreateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для создания задачи.

    Используется при назначении задачи работнику.
    """
    class Meta:
        model = Task
        fields = [
            'order', 'worker', 'assigned_by', 'is_self_assigned'
        ]

    def create(self, validated_data):
        return Task.objects.create(
            **validated_data,
            status=TaskStatus.PENDING
        )


class WorkRecordSerializer(serializers.ModelSerializer):
    """
    Сериализатор записи о работе с финансовыми данными.

    Используется только для владельца (owner).
    Включает стоимость труда.
    """
    worker_name = serializers.CharField(source='worker.username', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    confirmed_by_name = serializers.CharField(source='confirmed_by.username', read_only=True)

    class Meta:
        model = WorkRecord
        fields = [
            'id', 'task', 'worker', 'worker_name',
            'product', 'product_name', 'quantity', 'unit',
            'photo', 'comment', 'status',
            'confirmed_by', 'confirmed_by_name', 'confirmed_at',
            'rejection_reason', 'labor_cost',
            'is_confirmed', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'confirmed_at']


class WorkRecordLimitedSerializer(serializers.ModelSerializer):
    """
    Сериализатор записи о работе без финансовых данных.

    Используется для администраторов и работников.
    Исключает стоимость труда.
    """
    worker_name = serializers.CharField(source='worker.username', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    confirmed_by_name = serializers.CharField(source='confirmed_by.username', read_only=True)

    class Meta:
        model = WorkRecord
        fields = [
            'id', 'task', 'worker', 'worker_name',
            'product', 'product_name', 'quantity', 'unit',
            'photo', 'comment', 'status',
            'confirmed_by', 'confirmed_by_name', 'confirmed_at',
            'rejection_reason',
            'is_confirmed', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'confirmed_at']


class WorkRecordCreateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для создания записи о работе.

    Используется работником при выполнении работы.
    """
    class Meta:
        model = WorkRecord
        fields = [
            'task', 'worker', 'product', 'quantity', 'unit',
            'photo', 'comment'
        ]

    def create(self, validated_data):
        return WorkRecord.objects.create(
            **validated_data,
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION
        )
