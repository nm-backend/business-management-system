"""
Serializers for clients API.

ClientAdminSerializer - для администратора: только булевы статусы оплаты,
без сумм. ClientOwnerSerializer - полная финансовая карточка клиента.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from rest_framework import serializers

from apps.core.validators import validate_phone
from apps.orders.models import Order

from .models import Client, Payment


class PaymentSerializer(serializers.ModelSerializer):
    """Сериализатор оплаты клиента."""
    received_by_name = serializers.CharField(source='received_by.username', read_only=True)

    class Meta:
        model = Payment
        fields = [
            'id', 'client', 'order', 'amount', 'payment_method',
            'comment', 'received_by', 'received_by_name', 'payment_date',
            'created_at',
        ]
        read_only_fields = ['received_by', 'created_at']


class ClientAdminSerializer(serializers.ModelSerializer):
    """Сериализатор клиента для admin — с has_debt и has_active_orders без сумм."""
    has_debt = serializers.BooleanField(read_only=True)
    # DRF не подхватывает field-валидаторы с модели: без явного валидатора
    # телефон «привет» спокойно сохранялся через API (в админке ModelForm
    # валидировал), и по контакту нельзя было позвонить.
    phone = serializers.CharField(validators=[validate_phone], required=False, allow_blank=True)
    # Читаем аннотацию active_orders_exists (см. ClientViewSet.get_queryset) вместо
    # свойства has_active_orders, которое делало .exists() на каждого клиента (N+1).
    # Формат ответа не меняется: ключ в JSON остаётся has_active_orders.
    has_active_orders = serializers.SerializerMethodField()
    # Тип и ответственный — операционные данные, не финансовые: их видит и
    # администратор (сумм в карточке у него по-прежнему нет).
    client_type_display = serializers.CharField(source='get_client_type_display', read_only=True)
    responsible_employee_name = serializers.SerializerMethodField()

    def get_responsible_employee_name(self, obj):
        employee = obj.responsible_employee
        if not employee:
            return ''
        return employee.full_name or employee.username

    def validate_responsible_employee(self, employee):
        """Ответственный обязан быть сотрудником этой же компании."""
        request = self.context.get('request')
        company_id = getattr(getattr(request, 'user', None), 'company_id', None)
        if employee is not None and company_id is not None and employee.company_id != company_id:
            raise serializers.ValidationError('Сотрудник другой компании.')
        return employee

    class Meta:
        model = Client
        fields = [
            'id', 'name', 'phone', 'address', 'comment', 'is_archived',
            'client_type', 'client_type_display',
            'responsible_employee', 'responsible_employee_name',
            'has_debt', 'has_active_orders', 'created_at', 'updated_at',
        ]
        # Архивацию делают действия archive/restore: они зовут методы модели и
        # проставляют archived_at. Прямой PATCH is_archived их обходил и
        # оставлял «когда убрали в архив» пустым.
        read_only_fields = ['is_archived']

    def get_has_active_orders(self, obj):
        annotated = getattr(obj, 'active_orders_exists', None)
        return annotated if annotated is not None else obj.has_active_orders


class ClientOwnerSerializer(ClientAdminSerializer):
    """Сериализатор клиента для владельца — с полной финансовой карточкой."""
    payments = PaymentSerializer(many=True, read_only=True)
    # Прибыль по выданным заказам: читает аннотацию profit из get_queryset
    # (один SQL-запрос на весь список). Fallback ниже — для прямого вызова
    # сериализатора без аннотации (тесты/админка): считается тем же правилом.
    profit = serializers.SerializerMethodField()

    class Meta(ClientAdminSerializer.Meta):
        fields = ClientAdminSerializer.Meta.fields + [
            'total_orders_amount', 'total_paid', 'debt', 'profit', 'payments',
        ]
        # Производные финполя считает recalculate_financials из заказов/платежей.
        # Прямой записи через API быть не должно — иначе owner PATCH-ем подменял
        # бы долг клиента (искажение отчётов) до следующего пересчёта.
        read_only_fields = ClientAdminSerializer.Meta.read_only_fields + [
            'total_orders_amount', 'total_paid', 'debt', 'profit',
        ]

    def get_profit(self, obj):
        annotated = getattr(obj, 'profit', None)
        if annotated is not None:
            profit = annotated
        else:
            delivered = obj.orders.filter(
                status=Order.Status.DELIVERED,
                is_archived=False,
            )
            revenue = delivered.aggregate(s=Sum('total_amount'))['s'] or Decimal('0')
            cogs = delivered.aggregate(
                s=Sum(ExpressionWrapper(
                    F('quantity') * F('cost_price'),
                    output_field=DecimalField(max_digits=15, decimal_places=2),
                )),
            )['s'] or Decimal('0')
            profit = revenue - cogs
        # Строка, как остальные денежные поля (DecimalField с COERCE_DECIMAL_TO_STRING):
        # float потерял бы копейки на больших суммах (метод-поля минуют DecimalField).
        return '{:.2f}'.format(profit)
