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
    has_active_orders = serializers.BooleanField(read_only=True)

    class Meta:
        model = Client
        fields = [
            'id', 'name', 'phone', 'address', 'comment', 'is_archived',
            'has_debt', 'has_active_orders', 'created_at', 'updated_at',
        ]


class ClientOwnerSerializer(ClientAdminSerializer):
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta(ClientAdminSerializer.Meta):
        fields = ClientAdminSerializer.Meta.fields + [
            'total_orders_amount', 'total_paid', 'debt', 'payments',
        ]
