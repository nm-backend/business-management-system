from rest_framework import serializers
from django.db.models import Sum
from .models import Client, Payment

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = '__all__'

class ClientAdminSerializer(serializers.ModelSerializer):
    has_debt = serializers.SerializerMethodField()
    has_active_orders = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = ['id', 'name', 'phone', 'address', 'comment', 'is_archived', 'has_debt', 'has_active_orders', 'created_at', 'updated_at']

    def get_has_debt(self, obj):
        # Admin only sees boolean status
        # Logic to be fleshed out with real orders, mock for now
        return False

    def get_has_active_orders(self, obj):
        return False

class ClientOwnerSerializer(ClientAdminSerializer):
    total_debt = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()

    class Meta(ClientAdminSerializer.Meta):
        fields = ClientAdminSerializer.Meta.fields + ['total_debt', 'total_paid']

    def get_total_debt(self, obj):
        # Real logic depends on orders
        return 0

    def get_total_paid(self, obj):
        total = obj.payments.aggregate(total=Sum('amount'))['total']
        return total or 0
