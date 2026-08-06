"""
Serializers for production API.

Этот модуль содержит сериализаторы для моделей Task и WorkRecord
с защитой финансовых данных для non-owner пользователей.
"""
from rest_framework import serializers

from apps.core.validators import validate_file_size
from .models import Task, WorkPhoto, WorkRecord


class WorkPhotoSerializer(serializers.ModelSerializer):
    """Снимок из галереи работы — только чтение, отдаём URL."""

    class Meta:
        model = WorkPhoto
        fields = ['id', 'image', 'created_at']


class TaskSerializer(serializers.ModelSerializer):
    """
    Сериализатор задачи.

    Используется для всех ролей.
    Финансовых полей нет.
    """
    order_id = serializers.IntegerField(source='order.id', read_only=True)
    order_product = serializers.SerializerMethodField()
    worker_name = serializers.SerializerMethodField()
    assigned_by_name = serializers.CharField(source='assigned_by.username', read_only=True)
    confirmed_by_name = serializers.CharField(source='confirmed_by.username', read_only=True)

    def get_order_product(self, obj):
        if not obj.order:
            return ''
        if obj.order.product:
            return obj.order.product.name
        return obj.order.custom_product_name

    def get_worker_name(self, obj):
        return obj.worker.full_name or obj.worker.username

    class Meta:
        model = Task
        fields = [
            'id', 'order', 'order_id', 'order_product', 'worker', 'worker_name',
            'assigned_by', 'assigned_by_name', 'status',
            'refusal_reason', 'refusal_comment',
            'assigned_at', 'accepted_at', 'completed_at',
            'confirmed_at', 'confirmed_by', 'confirmed_by_name',
            'rejection_comment', 'is_self_assigned'
        ]
        # status/worker/order и т.п. меняются только через действия
        # (accept/refuse/cancel/confirm) и perform_create, а не прямым PATCH.
        read_only_fields = [
            'status', 'worker', 'order', 'assigned_by', 'confirmed_by',
            'is_self_assigned',
            'assigned_at', 'accepted_at', 'completed_at', 'confirmed_at',
        ]


class TaskCreateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для создания задачи.

    Используется при назначении задачи работнику.
    """
    class Meta:
        model = Task
        fields = ['order', 'worker', 'is_self_assigned']


class _ConfirmedWorkGuardMixin:
    """
    Защита подтверждённой работы от правки количества/брака через PATCH.

    confirm_work уже списал сырьё и приходовал товар по (quantity + defect_quantity)
    и начислил labor_cost. Прямая правка этих полей после подтверждения
    рассинхронизировала бы склад и заработок: склад остался по старым значениям,
    а цифры в карточке показали бы новые.
    """
    _CONFIRMED_LOCKED_FIELDS = ('quantity', 'defect_quantity')

    def validate(self, attrs):
        instance = self.instance
        if instance and instance.status == WorkRecord.WorkStatus.CONFIRMED:
            for field in self._CONFIRMED_LOCKED_FIELDS:
                if field in attrs and attrs[field] != getattr(instance, field):
                    raise serializers.ValidationError({
                        field: 'Количество подтверждённой работы изменить нельзя.',
                    })
        return attrs

    def validate_quantity(self, value):
        # Та же защита, что у Create-сериализатора: отрицательное количество
        # при PATCH до подтверждения испортило бы расчёты confirm_work.
        if value is None or value <= 0:
            raise serializers.ValidationError('Количество работы должно быть больше нуля.')
        return value


class WorkRecordSerializer(_ConfirmedWorkGuardMixin, serializers.ModelSerializer):
    """
    Сериализатор записи о работе с финансовыми данными.

    Используется только для владельца (owner).
    Включает стоимость труда.
    """
    worker_name = serializers.CharField(source='worker.username', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    confirmed_by_name = serializers.CharField(source='confirmed_by.username', read_only=True)
    photos = WorkPhotoSerializer(many=True, read_only=True)
    labor_rate = serializers.SerializerMethodField()

    def get_labor_rate(self, obj):
        """Ставка за единицу по операции работы (та же логика, что в calculate_labor_cost)."""
        from apps.finance.models import LaborRate
        if not obj.product:
            return None
        rates = list(obj.product.labor_rates.all())
        if not rates:
            return None
        if obj.operation:
            rate = next((r for r in rates if r.operation == obj.operation), None)
        elif len(rates) == 1:
            rate = rates[0]
        else:
            rate = None
        return str(rate.rate_per_unit) if rate else None

    class Meta:
        model = WorkRecord
        fields = [
            'id', 'task', 'worker', 'worker_name',
            'product', 'product_name', 'operation', 'quantity', 'defect_quantity', 'unit',
            'photo', 'photos', 'comment', 'status',
            'confirmed_by', 'confirmed_by_name', 'confirmed_at',
            'rejection_reason', 'labor_cost', 'labor_rate',
            'is_confirmed', 'created_at', 'updated_at'
        ]
        # status/labor_cost/worker меняются ТОЛЬКО через confirm/reject, а не PATCH.
        read_only_fields = [
            'status', 'labor_cost', 'worker', 'task', 'confirmed_by',
            'rejection_reason', 'created_at', 'updated_at', 'confirmed_at',
        ]


class WorkRecordLimitedSerializer(_ConfirmedWorkGuardMixin, serializers.ModelSerializer):
    """
    Сериализатор записи о работе без финансовых данных.

    Используется для администраторов и работников.
    Исключает стоимость труда.
    """
    worker_name = serializers.CharField(source='worker.username', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    confirmed_by_name = serializers.CharField(source='confirmed_by.username', read_only=True)
    photos = WorkPhotoSerializer(many=True, read_only=True)
    labor_rate = serializers.SerializerMethodField()

    def get_labor_rate(self, obj):
        from apps.finance.models import LaborRate
        if not obj.product:
            return None
        rates = list(obj.product.labor_rates.all())
        if not rates:
            return None
        if obj.operation:
            rate = next((r for r in rates if r.operation == obj.operation), None)
        elif len(rates) == 1:
            rate = rates[0]
        else:
            rate = None
        return str(rate.rate_per_unit) if rate else None

    class Meta:
        model = WorkRecord
        fields = [
            'id', 'task', 'worker', 'worker_name',
            'product', 'product_name', 'operation', 'quantity', 'defect_quantity', 'unit',
            'photo', 'photos', 'comment', 'status',
            'confirmed_by', 'confirmed_by_name', 'confirmed_at',
            'rejection_reason', 'labor_rate',
            'is_confirmed', 'created_at', 'updated_at'
        ]
        # Админ видит работы без денег и не может менять статус прямым PATCH.
        read_only_fields = [
            'status', 'worker', 'task', 'confirmed_by',
            'rejection_reason', 'created_at', 'updated_at', 'confirmed_at',
        ]


class WorkRecordCreateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для создания записи о работе.

    Используется работником при выполнении работы.
    """
    # Галерея: рабочий прикладывает несколько снимков (макет «Ишни якунлаш»).
    # Правило мягкое — работу без фото принимаем, админ видит пометку и решает
    # сам: рабочий без камеры или со слабым интернетом не должен застрять.
    uploaded_photos = serializers.ListField(
        child=serializers.ImageField(validators=[validate_file_size]),
        write_only=True, required=False, allow_empty=True,
    )

    class Meta:
        model = WorkRecord
        fields = [
            'task', 'worker', 'product', 'operation', 'quantity', 'defect_quantity', 'unit',
            'photo', 'uploaded_photos', 'comment'
        ]
        extra_kwargs = {'worker': {'required': False}}

    def create(self, validated_data):
        photos = validated_data.pop('uploaded_photos', [])
        work = super().create(validated_data)
        if photos:
            WorkPhoto.objects.bulk_create(
                [WorkPhoto(work=work, image=image) for image in photos]
            )
        elif work.photo:
            # Совместимость со старым одиночным полем: снимок тоже попадает в
            # галерею, иначе интерфейс его не покажет.
            WorkPhoto.objects.create(work=work, image=work.photo)
        return work

    def validate_quantity(self, value):
        # Отрицательное/нулевое количество портит склад при подтверждении:
        # требования по рецепту становятся отрицательными, проверка нехватки
        # сырья не срабатывает, остаток «дорисовывается», а labor_cost уходит
        # в минус. Отсекаем на входе.
        if value is None or value <= 0:
            raise serializers.ValidationError('Количество работы должно быть больше нуля.')
        return value
