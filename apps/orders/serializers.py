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
    has_product_shortage = serializers.SerializerMethodField()
    product_shortage = serializers.SerializerMethodField()
    is_overdue = serializers.BooleanField(read_only=True)
    client_name = serializers.CharField(source='client.name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    worker_name = serializers.SerializerMethodField()

    def validate(self, attrs):
        """
        Заказ обязан указывать товар: позицию каталога или название вручную.

        Воспроизведено: POST без product и без custom_product_name отвечал 201.
        Такой заказ не просто «пустая строка в списке» — у него нет рецепта,
        поэтому он ничего не резервирует (Order.reserve_product выходит на
        `if not self.product_id`), не попадает в расчёт нехватки материалов и
        не может быть корректно выдан.

        Оба поля остаются необязательными по отдельности: изделие «по описанию»
        каталожной позиции не имеет и живёт в custom_product_name.
        """
        instance = self.instance
        product = attrs.get('product', getattr(instance, 'product', None))
        custom = attrs.get('custom_product_name',
                           getattr(instance, 'custom_product_name', '') or '')
        if not product and not custom.strip():
            raise serializers.ValidationError({
                'product': 'Выберите товар из каталога или впишите название вручную.',
            })
        return attrs

    def validate_deadline(self, value):
        """
        Новый заказ нельзя создать с уже прошедшим сроком.

        Воспроизведено: API принимал заказ со сроком 2020-01-01 — он сразу
        попадал в «просроченные» и портил показатель просрочки на дашборде.
        У существующего заказа срок менять можно: его переносят и задним числом.
        """
        from django.utils import timezone

        if value and self.instance is None and value < timezone.now():
            raise serializers.ValidationError('Срок выполнения не может быть в прошлом.')
        return value

    class Meta:
        model = Order
        fields = [
            'id', 'client', 'client_name', 'product', 'product_name', 'custom_product_name',
            'quantity', 'unit', 'deadline', 'worker', 'worker_name', 'comment', 'photo',
            'status', 'payment_status', 'has_material_shortage', 'material_shortages',
            'has_product_shortage', 'product_shortage',
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

    def get_product_shortage(self, obj):
        """
        Нехватка ГОТОВОГО товара (в отличие от material_shortages — сырья).

        Сравниваем с тем, что реально будет доступно при выдаче: сначала
        снимается собственный резерв заказа (release_product), затем
        record_outgoing проверяет quantity <= quantity - reserved. Итоговое
        условие блока выдачи: reserved_for_orders > quantity, т.е. заказы
        зарезервировали больше, чем лежит на складе. Воспроизведено на
        равном количестве: заказ 10 из 10 помечался «нехваткой», хотя при
        выдаче резерв снимается и выдать такой заказ можно.

        Раньше о нехватке товара узнавали только при выдаче (record_outgoing
        отдаёт 400) — при создании заказа предупреждения не было вовсе, и
        администратор заказывал клиенту то, чего на складе нет.
        """
        if not obj.product_id or not obj.quantity:
            return None
        p = obj.product
        available = p.quantity - (p.reserved_for_orders - obj.quantity)
        if obj.quantity > available:
            return {
                'product_name': p.name,
                'required': obj.quantity,
                'available': max(available, 0),
                'unit': obj.unit,
            }
        return None

    def get_has_product_shortage(self, obj):
        return self.get_product_shortage(obj) is not None


class OrderOwnerSerializer(OrderSerializer):
    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + ['total_amount', 'paid_amount']
        # paid_amount — вычисляемое поле (Order.apply_payment_amount из платежей),
        # прямой записи быть не должно: иначе заказ помечался бы «оплачен» без
        # реального платежа. total_amount — вход владельца, остаётся записываемым.
        read_only_fields = OrderSerializer.Meta.read_only_fields + ['paid_amount']
