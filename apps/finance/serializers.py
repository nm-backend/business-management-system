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


class _SalaryCapMixin:
    """
    «Зарплата» — это выплата заработанного: сумма не может быть больше
    начисленного (labor_cost подтверждённых работ) минус уже выданное.
    Иначе баланс работника на странице расчётов уходит в минус, а владелец
    мог просто опечататься в сумме в разы. Аванс/премия/прочее — свободные
    выплаты, им потолка нет (аванс по определению выдаётся ДО работы).
    """
    def _validate_salary_cap(self, attrs):
        from decimal import Decimal

        from django.db.models import Sum

        from apps.production.models import WorkRecord

        from .models import WorkerPayment

        payment_type = attrs.get('payment_type', WorkerPayment.PaymentType.SALARY)
        if payment_type != WorkerPayment.PaymentType.SALARY:
            return
        worker = attrs.get('worker') or (self.instance.worker if self.instance else None)
        if worker is None:
            return
        current = self.instance.amount if self.instance else Decimal('0')
        accrued = WorkRecord.objects.filter(
            company_id=worker.company_id, worker=worker, status=WorkRecord.WorkStatus.CONFIRMED,
        ).aggregate(s=Sum('labor_cost'))['s'] or Decimal('0')
        paid = (
            WorkerPayment.objects.filter(company_id=worker.company_id, worker=worker)
            .exclude(pk=self.instance.pk if self.instance else None)
            .aggregate(s=Sum('amount'))['s'] or Decimal('0')
        )
        balance = Decimal(accrued) - Decimal(paid)
        amount = attrs.get('amount', current)
        if amount is None:
            return
        # Запрещаем только превышение СВЕРХ уже имеющегося: существующую
        # переплату не наращиваем, но и не блокируем её сохранение как есть
        # (например, при смене работника в записи).
        if Decimal(amount) > max(balance, Decimal('0')) and Decimal(amount) > current:
            raise serializers.ValidationError({
                'amount': 'Сумма зарплаты превышает начисленное '
                          '(начислено {0}, уже выдано {1}). Аванс или премию '
                          'проводите с соответствующим типом выплаты.'.format(
                              accrued, paid),
            })


class WorkerPaymentSerializer(_SalaryCapMixin, serializers.ModelSerializer):
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

    def validate(self, attrs):
        attrs = super().validate(attrs)
        self._validate_salary_cap(attrs)
        return attrs


class WorkerPaymentCreateSerializer(_SalaryCapMixin, serializers.ModelSerializer):
    """
    Сериализатор для создания выплаты работнику.

    Используется при выплате зарплаты/аванса.
    """
    class Meta:
        model = WorkerPayment
        fields = [
            # id в ответе создания: без него клиент не мог сразу PATCH/удалить
            # только что созданную выплату (перезагрузка списка вручную).
            'id', 'worker', 'amount', 'payment_date', 'payment_type', 'comment'
        ]
    # created_by и company проставляет ViewSet.perform_create.

    def validate(self, attrs):
        attrs = super().validate(attrs)
        self._validate_salary_cap(attrs)
        return attrs
