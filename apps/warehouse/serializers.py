from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.core.validators import validate_not_future
from .models import (
    FinishedProduct, RawMaterial, Recipe, RecipeItem, StockMovement,
    Warehouse, WarehouseCell,
)


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

class ReturnSerializer(serializers.Serializer):
    """
    Вход операции возврата на склад (вкладка «Қайтарилган»).

    Отдельно от прихода: возврат не поставка, среднюю себестоимость он не
    меняет и в закупки не попадает.
    """
    quantity = serializers.DecimalField(max_digits=15, decimal_places=3, min_value=Decimal('0.001'))
    return_date = serializers.DateField(required=False, validators=[validate_not_future])
    document_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)


class WarehouseCellSerializer(serializers.ModelSerializer):
    """
    Ячейка хранения с занятостью (макет «Омбордаги жойлашув»: А-01…А-08).

    Занятость только для чтения: её считает сервер по размещённым материалам,
    руками введённая цифра сразу разошлась бы с приходами и расходами.
    """
    zone_display = serializers.CharField(source='get_zone_display', read_only=True)
    occupied_area = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    occupancy_percent = serializers.DecimalField(max_digits=6, decimal_places=1, read_only=True)
    materials_count = serializers.SerializerMethodField()

    class Meta:
        model = WarehouseCell
        fields = [
            'id', 'warehouse', 'code', 'zone', 'zone_display', 'capacity_area',
            'occupied_area', 'occupancy_percent', 'materials_count',
            'is_archived', 'created_at', 'updated_at',
        ]
        read_only_fields = ['is_archived']

    def get_materials_count(self, obj):
        return obj.materials.filter(is_archived=False).count()


class WarehouseSerializer(serializers.ModelSerializer):
    """Склад компании с суммарной занятостью (макет «Асосий омбор»)."""
    occupied_area = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    occupancy_percent = serializers.DecimalField(max_digits=6, decimal_places=1, read_only=True)
    free_percent = serializers.SerializerMethodField()
    cells_count = serializers.SerializerMethodField()
    materials_count = serializers.SerializerMethodField()

    class Meta:
        model = Warehouse
        fields = [
            'id', 'name', 'code', 'address', 'total_area', 'is_default', 'comment',
            'occupied_area', 'occupancy_percent', 'free_percent',
            'cells_count', 'materials_count', 'is_archived',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['is_archived']

    def get_free_percent(self, obj):
        """Свободно — то, что осталось до 100 % (макет показывает обе цифры)."""
        free = Decimal('100') - obj.occupancy_percent
        return max(free, Decimal('0')).quantize(Decimal('0.1'))

    def get_cells_count(self, obj):
        return obj.cells.filter(is_archived=False).count()

    def get_materials_count(self, obj):
        return obj.materials.filter(is_archived=False).count()


class RawMaterialSerializer(StockQuantityGuardMixin, serializers.ModelSerializer):
    """Сериализатор сырья — admin/worker видит количество без цен."""
    unit_display = serializers.CharField(source='get_unit_display', read_only=True)
    storage_zone_display = serializers.CharField(source='get_storage_zone_display', read_only=True)
    condition_display = serializers.CharField(source='get_condition_display', read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)
    # Градация остатка: «критично» отличается от «ниже минимума» (макет
    # «Минимум қолдиқлар»), раньше был только булев флаг.
    stock_severity = serializers.CharField(read_only=True)
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True, default='')
    cell_code = serializers.CharField(source='cell.code', read_only=True, default='')
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
            'warehouse', 'warehouse_name', 'cell', 'cell_code', 'occupied_area',
            'condition', 'condition_display',
            'required_for_orders', 'available_quantity',
            'photo', 'min_stock', 'supplier', 'arrival_date',
            'comment', 'is_archived', 'is_low_stock', 'stock_severity',
            'created_at', 'updated_at'
        ]

    def validate(self, attrs):
        """
        Склад и ячейка — только свои, и ячейка обязана принадлежать складу.

        Без проверки материал можно было положить в ячейку чужой компании
        (её занятость поехала бы) или в ячейку другого склада — карта
        размещения показывала бы материал не там, где он лежит.
        """
        request = self.context.get('request')
        company_id = getattr(getattr(request, 'user', None), 'company_id', None)
        warehouse = attrs.get('warehouse', getattr(self.instance, 'warehouse', None))
        cell = attrs.get('cell', getattr(self.instance, 'cell', None))

        if company_id is not None:
            if warehouse and warehouse.company_id != company_id:
                raise serializers.ValidationError({'warehouse': 'Склад другой компании.'})
            if cell and cell.company_id != company_id:
                raise serializers.ValidationError({'cell': 'Ячейка другой компании.'})
        if cell and warehouse and cell.warehouse_id != warehouse.id:
            raise serializers.ValidationError({
                'cell': 'Ячейка принадлежит другому складу.',
            })
        if cell and not warehouse:
            # Ячейка без склада — потерянное размещение; подставляем её склад.
            attrs['warehouse'] = cell.warehouse
        return attrs


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
    """
    Сериализатор компонента рецепта.

    Единица позиции обязана совпадать с единицей материала. Расход по рецепту
    вычитается из остатка КАК ЕСТЬ (см. get_recipe_requirements: количество
    просто умножается на объём партии), пересчёта единиц в системе нет.
    Поэтому «2 кг» у материала, который меряется в м², молча списали бы 2 м²:
    остаток, себестоимость и расчёт нехватки поехали бы, а в карточке рецепта
    рядом стояли бы «требуется 2 кг» и «доступно 100 м²».

    Интерфейс единицу не присылает вовсе — раньше подставлялся дефолт модели
    («шт»), из-за чего несовпадение возникало на каждом рецепте, созданном из
    карточки товара. Теперь единица берётся у материала.
    """
    material_name = serializers.CharField(source='material.name', read_only=True)
    unit_display = serializers.CharField(source='get_unit_display', read_only=True)

    class Meta:
        model = RecipeItem
        fields = '__all__'

    def validate(self, attrs):
        material = attrs.get('material') or getattr(self.instance, 'material', None)
        if material is None:
            return attrs

        unit = attrs.get('unit')
        if unit is None:
            # Единицу не прислали (обычный случай из интерфейса) — берём у материала.
            attrs['unit'] = material.unit
        elif unit != material.unit:
            raise serializers.ValidationError({
                'unit': (
                    f'Единица позиции рецепта ({unit}) не совпадает с единицей '
                    f'материала «{material.name}» ({material.unit}). Пересчёта '
                    f'единиц нет: расход списывается в единицах материала.'
                ),
            })
        return attrs

class RecipeSerializer(serializers.ModelSerializer):
    """Сериализатор рецепта с вложенными компонентами."""
    items = RecipeItemSerializer(many=True, read_only=True)

    class Meta:
        model = Recipe
        fields = '__all__'
        # company проставляет сервер (из request.user), клиент не задаёт — иначе
        # владелец мог PATCH-ем перекинуть рецепт в чужую компанию (mass assignment).
        read_only_fields = ['company']
