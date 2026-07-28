from decimal import Decimal

from rest_framework import serializers

from apps.core.validators import validate_not_future
from .models import RawMaterial, FinishedProduct, StockMovement, Recipe, RecipeItem


class IncomingSerializer(serializers.Serializer):
    """
    Вход операции прихода: сколько пришло, по какой цене и когда.

    quantity строго больше нуля: приход на 0 или отрицательный — это не приход,
    а списание, для которого есть свои операции.
    """
    quantity = serializers.DecimalField(max_digits=15, decimal_places=3, min_value=Decimal('0.001'))
    price_per_unit = serializers.DecimalField(max_digits=15, decimal_places=2,
                                              min_value=Decimal('0'), required=False)
    arrival_date = serializers.DateField(required=False, validators=[validate_not_future])
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)

class RawMaterialSerializer(serializers.ModelSerializer):
    unit_display = serializers.CharField(source='get_unit_display', read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = RawMaterial
        fields = [
            'id', 'name', 'stone_type', 'color', 'size', 'thickness',
            'unit', 'unit_display', 'quantity', 'storage_location',
            'photo', 'min_stock', 'supplier', 'arrival_date',
            'comment', 'is_archived', 'is_low_stock',
            'created_at', 'updated_at'
        ]

class RawMaterialOwnerSerializer(RawMaterialSerializer):
    class Meta(RawMaterialSerializer.Meta):
        fields = RawMaterialSerializer.Meta.fields + ['purchase_price', 'avg_cost_price']

class FinishedProductSerializer(serializers.ModelSerializer):
    unit_display = serializers.CharField(source='get_unit_display', read_only=True)
    available_quantity = serializers.DecimalField(max_digits=15, decimal_places=3, read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = FinishedProduct
        fields = [
            'id', 'name', 'category', 'unit', 'unit_display',
            'quantity', 'photo', 'description', 'min_stock',
            'reserved_for_orders', 'available_quantity',
            'is_archived', 'is_low_stock',
            'created_at', 'updated_at'
        ]

    def validate(self, attrs):
        """
        Резерв не может превышать остаток.

        available_quantity считается как quantity - reserved_for_orders, поэтому
        резерв больше остатка давал ОТРИЦАТЕЛЬНОЕ доступное количество и ломал
        признак нехватки товара (воспроизведено: остаток 1, резерв 100 -> API
        принимал запись).
        """
        instance = self.instance
        quantity = attrs.get('quantity', getattr(instance, 'quantity', None))
        reserved = attrs.get('reserved_for_orders', getattr(instance, 'reserved_for_orders', None))
        if quantity is not None and reserved is not None and reserved > quantity:
            raise serializers.ValidationError({
                'reserved_for_orders': f'Резерв не может превышать остаток ({quantity}).'
            })
        return attrs

class FinishedProductOwnerSerializer(FinishedProductSerializer):
    class Meta(FinishedProductSerializer.Meta):
        fields = FinishedProductSerializer.Meta.fields + ['cost_price', 'sale_price']

class StockMovementSerializer(serializers.ModelSerializer):
    movement_type_display = serializers.CharField(source='get_movement_type_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    # Без названий история отдавала только id материала/товара — показывать
    # в списке было нечего.
    material_name = serializers.CharField(source='material.name', read_only=True, default='')
    product_name = serializers.CharField(source='product.name', read_only=True, default='')
    unit = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = '__all__'

    def get_unit(self, obj):
        target = obj.material or obj.product
        return target.unit if target else ''


class StockMovementLimitedSerializer(StockMovementSerializer):
    class Meta:
        model = StockMovement
        exclude = ['price_per_unit']


class RecipeItemSerializer(serializers.ModelSerializer):
    material_name = serializers.CharField(source='material.name', read_only=True)
    unit_display = serializers.CharField(source='get_unit_display', read_only=True)

    class Meta:
        model = RecipeItem
        fields = '__all__'

class RecipeSerializer(serializers.ModelSerializer):
    items = RecipeItemSerializer(many=True, read_only=True)

    class Meta:
        model = Recipe
        fields = '__all__'
        # company проставляет сервер (из request.user), клиент не задаёт — иначе
        # владелец мог PATCH-ем перекинуть рецепт в чужую компанию (mass assignment).
        read_only_fields = ['company']
