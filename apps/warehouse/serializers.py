from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.core.validators import validate_not_future
from .models import RawMaterial, FinishedProduct, StockMovement, Recipe, RecipeItem


class StockQuantityGuardMixin:
    """
    Остаток нельзя менять прямой правкой карточки — только операциями склада.
    """

    quantity_guarded_fields: tuple[str, ...] = ('quantity',)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.instance is not None:
            for name in self.quantity_guarded_fields:
                if name in self.fields:
                    self.fields[name].read_only = True


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
    # Номер документа прихода (макет: «Хужжат раками»).
    document_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)

class OutgoingSerializer(serializers.Serializer):
    """
    Вход операции расхода/списания сырья (макет «Материални чиқариш»).

    quantity строго больше нуля. outgoing_date — дата списания (не в будущем).
    document_number — номер документа расхода. Списывается только доступное
    количество (quantity - required_for_orders): требуемое под заказы сырьё
    трогать нельзя, иначе под заказ не хватит материала.
    """
    quantity = serializers.DecimalField(max_digits=15, decimal_places=3, min_value=Decimal('0.001'))
    outgoing_date = serializers.DateField(required=False, validators=[validate_not_future])
    document_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)
    movement_type = serializers.ChoiceField(
        choices=[
            (StockMovement.MovementType.OUTGOING, StockMovement.MovementType.OUTGOING),
            (StockMovement.MovementType.LOSS, StockMovement.MovementType.LOSS),
            (StockMovement.MovementType.ADJUSTMENT, StockMovement.MovementType.ADJUSTMENT),
        ],
        default=StockMovement.MovementType.OUTGOING,
        required=False,
    )

class RawMaterialSerializer(StockQuantityGuardMixin, serializers.ModelSerializer):
    """Сериализатор сырья — admin/worker видит количество без цен."""
    unit_display = serializers.CharField(source='get_unit_display', read_only=True)
    storage_zone_display = serializers.CharField(source='get_storage_zone_display', read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)
    # Потребность сырья мутируется только бизнес-флоу (заказы, подтверждение
    # работ), а не обычным PATCH-ем: иначе сотрудник мог бы выставить произвольную
    # потребность и заблокировать расход. available_quantity — производное, только чтение.
    required_for_orders = serializers.DecimalField(
        max_digits=15, decimal_places=3, read_only=True)
    available_quantity = serializers.DecimalField(
        max_digits=15, decimal_places=3, read_only=True)

    class Meta:
        model = RawMaterial
        fields = [
            'id', 'name', 'stone_type', 'color', 'size', 'thickness',
            'unit', 'unit_display', 'quantity', 'barcode', 'storage_zone',
            'storage_zone_display', 'storage_location',
            'required_for_orders', 'available_quantity',
            'photo', 'min_stock', 'supplier', 'arrival_date',
            'comment', 'is_archived', 'is_low_stock',
            'created_at', 'updated_at'
        ]

class RawMaterialOwnerSerializer(RawMaterialSerializer):
    """Сериализатор сырья для владельца — с purchase_price и avg_cost_price."""
    class Meta(RawMaterialSerializer.Meta):
        fields = RawMaterialSerializer.Meta.fields + ['purchase_price', 'avg_cost_price']

class FinishedProductSerializer(StockQuantityGuardMixin, serializers.ModelSerializer):
    """Сериализатор готовой продукции — admin видит количество без цен."""
    unit_display = serializers.CharField(source='get_unit_display', read_only=True)
    available_quantity = serializers.DecimalField(max_digits=15, decimal_places=3, read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)
    # Потребность товара мутируется только заказами (apply/release), не PATCH-ем.
    required_for_orders = serializers.DecimalField(
        max_digits=15, decimal_places=3, read_only=True)

    class Meta:
        model = FinishedProduct
        fields = [
            'id', 'name', 'category', 'unit', 'unit_display',
            'quantity', 'photo', 'description', 'min_stock',
            'required_for_orders', 'available_quantity',
            'is_archived', 'is_low_stock',
            'created_at', 'updated_at'
        ]

class FinishedProductOwnerSerializer(FinishedProductSerializer):
    """Сериализатор готовой продукции для владельца — с cost_price, sale_price, labor_rate."""
    labor_rate = serializers.DecimalField(max_digits=15, decimal_places=2,
                                          min_value=Decimal('0'), required=False,
                                          allow_null=True)

    class Meta(FinishedProductSerializer.Meta):
        fields = FinishedProductSerializer.Meta.fields + ['cost_price', 'sale_price', 'labor_rate']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['labor_rate'] = str(self._card_rate(instance).rate_per_unit) if self._card_rate(instance) else None
        return data

    @staticmethod
    def _card_rate(product):
        """Ставка, которую видит и правит владелец в карточке товара.

        Раньше бралась ставка «по алфавиту» (order_by('operation')), а расчёт
        платит по операции работы (production.services.calculate_labor_cost).
        При нескольких операциях поле в карточке правило чужую ставку — владелец
        менял «резку», а работник получал по «полировке». Показываем ставку
        операции OTHER («другое»), а если её нет — единственную ставку товара.
        """
        from apps.finance.models import LaborRate

        rates = list(product.labor_rates.all())
        rate = next((r for r in rates if r.operation == LaborRate.OperationType.OTHER), None)
        if rate is None and len(rates) == 1:
            rate = rates[0]
        return rate

    def _save_labor_rate(self, product, value):
        """Одна ставка на товар: правим карточную или заводим первую."""
        from apps.finance.models import LaborRate

        rate = self._card_rate(product)
        if rate:
            rate.rate_per_unit = value
            rate.save(update_fields=['rate_per_unit', 'updated_at'])
        else:
            LaborRate.objects.create(
                company=product.company, product=product,
                operation=LaborRate.OperationType.OTHER,
                rate_per_unit=value, unit=product.unit,
            )

    def create(self, validated_data):
        rate = validated_data.pop('labor_rate', None)
        product = super().create(validated_data)
        if rate is not None:
            self._save_labor_rate(product, rate)
        return product

    def update(self, instance, validated_data):
        rate = validated_data.pop('labor_rate', None)
        product = super().update(instance, validated_data)
        if rate is not None:
            self._save_labor_rate(product, rate)
        return product

class StockMovementSerializer(serializers.ModelSerializer):
    """Сериализатор движения склада — полная информация для владельца."""
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
    """Сериализатор движения склада без price_per_unit — для admin/worker."""
    class Meta:
        model = StockMovement
        exclude = ['price_per_unit']


class RecipeItemSerializer(serializers.ModelSerializer):
    """Сериализатор компонента рецепта."""
    material_name = serializers.CharField(source='material.name', read_only=True)
    unit_display = serializers.CharField(source='get_unit_display', read_only=True)

    class Meta:
        model = RecipeItem
        fields = '__all__'

class RecipeSerializer(serializers.ModelSerializer):
    """Сериализатор рецепта с вложенными компонентами."""
    items = RecipeItemSerializer(many=True, read_only=True)

    class Meta:
        model = Recipe
        fields = '__all__'
        # company проставляет сервер (из request.user), клиент не задаёт — иначе
        # владелец мог PATCH-ем перекинуть рецепт в чужую компанию (mass assignment).
        read_only_fields = ['company']
