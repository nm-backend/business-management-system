"""
Serializers for orders API.

Суммы заказа (total_amount, paid_amount) видит только владелец:
OrderSerializer - для admin/worker, OrderOwnerSerializer - для owner.
"""
from rest_framework import serializers

from apps.production.services import check_material_shortages
from .models import Order


class OrderSerializer(serializers.ModelSerializer):
    has_material_shortage = serializers.SerializerMethodField()
    material_shortages = serializers.SerializerMethodField()
    is_overdue = serializers.BooleanField(read_only=True)
    client_name = serializers.CharField(source='client.name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    worker_name = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'client', 'client_name', 'product', 'product_name', 'custom_product_name',
            'quantity', 'unit', 'deadline', 'worker', 'worker_name', 'comment', 'photo',
            'status', 'payment_status', 'has_material_shortage', 'material_shortages',
            'is_overdue', 'created_at', 'updated_at',
        ]
        # status/payment_status меняются ТОЛЬКО через действия (deliver/cancel) и
        # производственный поток, а не прямым PATCH — иначе обходится конечный
        # автомат заказа и его side-эффекты (пересчёт финансов, авто-архив, уведомления).
        read_only_fields = ['status', 'payment_status']

    def get_worker_name(self, obj):
        if not obj.worker:
            return ''
        return obj.worker.full_name or obj.worker.username

    def get_material_shortages(self, obj):
        """Нехватка сырья по активному рецепту (без цен, только количества)."""
        if not hasattr(obj, '_shortages'):
            if not obj.product or obj.status in (Order.Status.DELIVERED, Order.Status.CANCELLED):
                obj._shortages = []
            else:
                obj._shortages = check_material_shortages(obj.product, obj.quantity)
        return obj._shortages

    def get_has_material_shortage(self, obj):
        return bool(self.get_material_shortages(obj))


class OrderOwnerSerializer(OrderSerializer):
    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + ['total_amount', 'paid_amount']
        # paid_amount — вычисляемое поле (Order.apply_payment_amount из платежей),
        # прямой записи быть не должно: иначе заказ помечался бы «оплачен» без
        # реального платежа. total_amount — вход владельца, остаётся записываемым.
        read_only_fields = OrderSerializer.Meta.read_only_fields + ['paid_amount']
