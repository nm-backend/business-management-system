"""
Serializers for clients API.

ClientAdminSerializer - для администратора: только булевы статусы оплаты,
без сумм. ClientOwnerSerializer - полная финансовая карточка клиента.
"""
from rest_framework import serializers

from .models import Client, Payment


class PaymentSerializer(serializers.ModelSerializer):
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
    has_debt = serializers.BooleanField(read_only=True)
    # Читаем аннотацию active_orders_exists (см. ClientViewSet.get_queryset) вместо
    # свойства has_active_orders, которое делало .exists() на каждого клиента (N+1).
    # Формат ответа не меняется: ключ в JSON остаётся has_active_orders.
    has_active_orders = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            'id', 'name', 'phone', 'address', 'comment', 'is_archived',
            'has_debt', 'has_active_orders', 'created_at', 'updated_at',
        ]

    def get_has_active_orders(self, obj):
        annotated = getattr(obj, 'active_orders_exists', None)
        return annotated if annotated is not None else obj.has_active_orders


class ClientOwnerSerializer(ClientAdminSerializer):
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta(ClientAdminSerializer.Meta):
        fields = ClientAdminSerializer.Meta.fields + [
            'total_orders_amount', 'total_paid', 'debt', 'payments',
        ]
        # Производные финполя считает recalculate_financials из заказов/платежей.
        # Прямой записи через API быть не должно — иначе owner PATCH-ем подменял
        # бы долг клиента (искажение отчётов) до следующего пересчёта.
        read_only_fields = ['total_orders_amount', 'total_paid', 'debt']
