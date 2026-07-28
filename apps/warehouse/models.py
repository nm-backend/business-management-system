"""
Warehouse models - управление складом сырья и готовой продукции.

Этот модуль содержит модели для управления:
- Сырьем (RawMaterial) - материалы для производства
- Готовой продукцией (FinishedProduct) - готовые изделия
- Движениями склада (StockMovement) - история изменений
- Рецептами (Recipe, RecipeItem) - состав продукции

ВАЖНО: Финансовые поля (цены) доступны только владельцу.
"""
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.core.exceptions import ValidationError
from apps.core.models import TimestampedModel, SoftDeleteModel
from apps.core.validators import validate_file_size, validate_not_future


class UnitChoices(models.TextChoices):
    """
    Единицы измерения для материалов и продукции.

    Используется для унификации единиц измерения во всей системе.

    Выборы:
        SHT: штук (шт)
        M: метр (м)
        M2: квадратный метр (м²)
        IZDELIE: изделие (изд)
        DONA: штука на узбекском (дона)
    """
    SHT = 'sht', 'Штук'
    M = 'm', 'Метр'
    M2 = 'm2', 'Квадратный метр'
    IZDELIE = 'izdelie', 'Изделие'
    DONA = 'dona', 'Дона'

class RawMaterial(TimestampedModel, SoftDeleteModel):
    """
    Модель сырья на складе.

    Хранит информацию о материалах, используемых в производстве.
    Поддерживает мягкое удаление и отслеживание низких остатков.

    Поля:
        name: CharField - название материала
        stone_type: CharField - тип камня (мрамор, гранит и т.д.)
        color: CharField - цвет материала
        size: CharField - размер
        thickness: CharField - толщина
        unit: CharField - единица измерения
        quantity: DecimalField - текущее количество
        storage_location: CharField - место хранения
        photo: ImageField - фото материала
        min_stock: DecimalField - минимальный остаток для предупреждений
        supplier: CharField - поставщик
        arrival_date: DateField - дата поступления
        comment: TextField - комментарий
        purchase_price: DecimalField - цена закупки (ФИНАНСОВОЕ ПОЛЕ - только owner)
        avg_cost_price: DecimalField - средняя себестоимость (ФИНАНСОВОЕ ПОЛЕ - только owner)

    Свойства:
        is_low_stock: bool - True если quantity <= min_stock

    Особенности:
        - Поддерживает мягкое удаление (SoftDeleteModel)
        - Автоматические временные метки (TimestampedModel)
    """
    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='raw_materials', null=True, verbose_name='Компания')
    name = models.CharField(max_length=255, verbose_name='Название')
    stone_type = models.CharField(max_length=100, blank=True, verbose_name='Вид камня')
    color = models.CharField(max_length=100, blank=True, verbose_name='Цвет')
    size = models.CharField(max_length=100, blank=True, verbose_name='Размер')
    thickness = models.CharField(max_length=50, blank=True, verbose_name='Толщина')
    unit = models.CharField(max_length=20, choices=UnitChoices.choices, default=UnitChoices.SHT, verbose_name='Единица измерения')
    quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0,
                                   validators=[MinValueValidator(Decimal('0'))], verbose_name='Количество')
    storage_location = models.CharField(max_length=255, blank=True, verbose_name='Место хранения')
    photo = models.ImageField(upload_to='materials/', blank=True, null=True, validators=[validate_file_size], verbose_name='Фото')
    min_stock = models.DecimalField(max_digits=15, decimal_places=3, default=0,
                                    validators=[MinValueValidator(Decimal('0'))], verbose_name='Минимальный остаток')
    supplier = models.CharField(max_length=255, blank=True, verbose_name='Поставщик')
    arrival_date = models.DateField(null=True, blank=True, validators=[validate_not_future],
                                    verbose_name='Дата поступления')
    comment = models.TextField(blank=True, verbose_name='Комментарий')
    purchase_price = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                         validators=[MinValueValidator(Decimal('0'))], verbose_name='Цена закупки')  # ФИНАНСОВОЕ ПОЛЕ
    avg_cost_price = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                         validators=[MinValueValidator(Decimal('0'))], verbose_name='Средняя себестоимость')  # ФИНАНСОВОЕ ПОЛЕ

    class Meta:
        """
        Метаданные модели RawMaterial.

        Атрибуты:
            verbose_name: человекочитаемое имя модели
            verbose_name_plural: множественное число
            ordering: сортировка по умолчанию
        """
        verbose_name = 'Сырьё (материал)'
        verbose_name_plural = 'Склад сырья'
        ordering = ['name']

    def __str__(self):
        """
        Строковое представление материала.

        Возвращает название с количеством и единицей измерения.
        """
        return f"{self.name} ({self.quantity} {self.get_unit_display()})"

    @property
    def is_low_stock(self):
        """
        Проверяет, находится ли материал на низком остатке.

        Возвращает:
            bool - True если quantity <= min_stock
        """
        return self.quantity <= self.min_stock

class FinishedProduct(TimestampedModel, SoftDeleteModel):
    """
    Модель готовой продукции на складе.

    Хранит информацию о готовых изделиях, доступных для продажи.
    Поддерживает резервирование под заказы.

    Поля:
        name: CharField - название продукции
        category: CharField - категория продукции
        unit: CharField - единица измерения
        quantity: DecimalField - общее количество на складе
        photo: ImageField - фото продукции
        description: TextField - описание
        min_stock: DecimalField - минимальный остаток для предупреждений
        reserved_for_orders: DecimalField - зарезервировано под заказы
        cost_price: DecimalField - себестоимость (ФИНАНСОВОЕ ПОЛЕ - только owner)
        sale_price: DecimalField - цена продажи (ФИНАНСОВОЕ ПОЛЕ - только owner)

    Свойства:
        available_quantity: DecimalField - доступное количество (quantity - reserved)
        is_low_stock: bool - True если available_quantity <= min_stock

    Особенности:
        - Поддерживает мягкое удаление (SoftDeleteModel)
        - Автоматические временные метки (TimestampedModel)
        - Резервирование под заказы для точного учета
    """
    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='finished_products', null=True, verbose_name='Компания')
    name = models.CharField(max_length=255, verbose_name='Название')
    category = models.CharField(max_length=100, blank=True, verbose_name='Категория')
    unit = models.CharField(max_length=20, choices=UnitChoices.choices, default=UnitChoices.IZDELIE, verbose_name='Единица измерения')
    quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0, verbose_name='Количество')
    photo = models.ImageField(upload_to='products/', blank=True, null=True, validators=[validate_file_size], verbose_name='Фото')
    description = models.TextField(blank=True, verbose_name='Описание')
    min_stock = models.DecimalField(max_digits=15, decimal_places=3, default=0, verbose_name='Минимальный остаток')
    reserved_for_orders = models.DecimalField(max_digits=15, decimal_places=3, default=0,
                                        validators=[MinValueValidator(Decimal('0'))], verbose_name='Зарезервировано под заказы')
    cost_price = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                        validators=[MinValueValidator(Decimal('0'))], verbose_name='Себестоимость')  # ФИНАНСОВОЕ ПОЛЕ
    sale_price = models.DecimalField(max_digits=15, decimal_places=2, default=0,
                                        validators=[MinValueValidator(Decimal('0'))], verbose_name='Цена продажи')  # ФИНАНСОВОЕ ПОЛЕ

    class Meta:
        """
        Метаданные модели FinishedProduct.

        Атрибуты:
            verbose_name: человекочитаемое имя модели
            verbose_name_plural: множественное число
            ordering: сортировка по умолчанию
        """
        verbose_name = 'Готовая продукция'
        verbose_name_plural = 'Готовая продукция'
        ordering = ['name']

    def __str__(self):
        """
        Строковое представление продукции.

        Возвращает название с количеством и единицей измерения.
        """
        return f"{self.name} ({self.quantity} {self.get_unit_display()})"

    @property
    def available_quantity(self):
        """
        Вычисляет доступное количество для продажи.

        Учитывает резервирование под заказы.

        Возвращает:
            DecimalField - quantity - reserved_for_orders
        """
        return self.quantity - self.reserved_for_orders

    @property
    def is_low_stock(self):
        """
        Проверяет, находится ли продукция на низком остатке.

        Учитывает доступное количество (с учетом резервов).

        Возвращает:
            bool - True если available_quantity <= min_stock
        """
        return self.available_quantity <= self.min_stock

class StockMovement(TimestampedModel):
    """
    Модель движения склада (аудит изменений).

    Записывает все изменения количества на складе для полной истории.
    Используется для отслеживания приходов, расходов, производства и корректировок.

    Поля:
        movement_type: CharField - тип движения (приход, расход, производство и т.д.)
        material: ForeignKey - ссылка на сырье (null если движение продукции)
        product: ForeignKey - ссылка на продукцию (null если движение сырья)
        quantity: DecimalField - количество движения
        price_per_unit: DecimalField - цена за единицу (ФИНАНСОВОЕ ПОЛЕ - только owner)
        reason: CharField - причина движения
        created_by: ForeignKey - пользователь, создавший запись
        related_order_id: IntegerField - ID связанного заказа (опционально)
        related_production_id: IntegerField - ID связанного производства (опционально)

    Валидация:
        - Движение должно быть связано либо с material, либо с product
        - Нельзя связывать одновременно с material и product

    Особенности:
        - Автоматические временные метки (TimestampedModel)
        - Не поддерживает мягкое удаление (история должна сохраняться)
    """

    class MovementType(models.TextChoices):
        """
        Типы движений склада.

        INCOMING: приход материалов
        OUTGOING: расход материалов
        PRODUCTION_IN: приход готовой продукции с производства
        PRODUCTION_OUT: расход материалов на производство
        ADJUSTMENT: корректировка остатков
        LOSS: потеря или брак
        """
        INCOMING = 'incoming', 'Приход'
        OUTGOING = 'outgoing', 'Расход'
        PRODUCTION_IN = 'production_in', 'Приход с производства'
        PRODUCTION_OUT = 'production_out', 'Расход на производство'
        ADJUSTMENT = 'adjustment', 'Корректировка'
        LOSS = 'loss', 'Потеря/Брак'

    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='stock_movements', null=True, verbose_name='Компания')
    movement_type = models.CharField(max_length=20, choices=MovementType.choices, db_index=True, verbose_name='Тип движения')
    material = models.ForeignKey(RawMaterial, on_delete=models.CASCADE, null=True, blank=True, related_name='movements', verbose_name='Материал')
    product = models.ForeignKey(FinishedProduct, on_delete=models.CASCADE, null=True, blank=True, related_name='movements', verbose_name='Товар')
    quantity = models.DecimalField(max_digits=15, decimal_places=3, verbose_name='Количество')
    price_per_unit = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name='Цена за единицу')
    reason = models.CharField(max_length=255, blank=True, verbose_name='Причина')
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='stock_movements', verbose_name='Кем создано')
    related_order_id = models.IntegerField(null=True, blank=True, verbose_name='ID связанного заказа')
    related_production_id = models.IntegerField(null=True, blank=True, verbose_name='ID связанного производства')

    class Meta:
        """
        Метаданные модели StockMovement.

        Атрибуты:
            verbose_name: человекочитаемое имя модели
            verbose_name_plural: множественное число
            ordering: сортировка по убыванию даты создания
        """
        verbose_name = 'Движение склада'
        verbose_name_plural = 'Движения склада'
        ordering = ['-created_at']

    def clean(self):
        """
        Валидирует движение склада.

        Проверяет, что движение связано либо с material, либо с product,
        но не с обоими одновременно.

        Исключения:
            ValidationError - если валидация не пройдена
        """
        if self.material and self.product:
            raise ValidationError("Movement must be associated with either material or product, not both.")
        if not self.material and not self.product:
            raise ValidationError("Movement must be associated with a material or a product.")

class Recipe(TimestampedModel):
    """
    Модель рецепта производства продукции.

    Определяет состав готовой продукции - какие материалы и в каком количестве
    необходимы для производства. Поддерживает несколько рецептов для одной продукции.

    Поля:
        product: ForeignKey - готовая продукция, для которой создан рецепт
        name: CharField - название рецепта
        description: TextField - описание рецепта
        is_active: BooleanField - активен ли рецепт (можно деактивировать старые рецепты)

    Особенности:
        - Автоматические временные метки (TimestampedModel)
        - Одна продукция может иметь несколько рецептов
        - Можно деактивировать старые рецепты вместо удаления
    """
    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='recipes', null=True, verbose_name='Компания')
    product = models.ForeignKey(FinishedProduct, on_delete=models.CASCADE, related_name='recipes', verbose_name='Товар')
    name = models.CharField(max_length=255, verbose_name='Название')
    description = models.TextField(blank=True, verbose_name='Описание')
    is_active = models.BooleanField(default=True, verbose_name='Активен')

    class Meta:
        """
        Метаданные модели Recipe.

        Атрибуты:
            verbose_name: человекочитаемое имя модели
            verbose_name_plural: множественное число
            ordering: сортировка по названию
        """
        verbose_name = 'Рецепт'
        verbose_name_plural = 'Рецепты'
        ordering = ['name']

    def __str__(self):
        """
        Строковое представление рецепта.

        Возвращает название рецепта с указанием продукции.
        """
        return f"Recipe for {self.product.name}: {self.name}"


class RecipeItem(models.Model):
    """
    Модель элемента рецепта (ингредиент).

    Определяет какой материал и в каком количестве требуется
    для производства по рецепту.

    Поля:
        recipe: ForeignKey - рецепт, к которому относится ингредиент
        material: ForeignKey - материал (сырье)
        quantity_required: DecimalField - требуемое количество
        unit: CharField - единица измерения

    Особенности:
        - RESTRICT при удалении материала (нельзя удалить материал, используемый в рецептах)
        - Не имеет временных меток (ингредиент является частью рецепта)
    """
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name='items', verbose_name='Рецепт')
    material = models.ForeignKey(RawMaterial, on_delete=models.RESTRICT, verbose_name='Материал')
    quantity_required = models.DecimalField(max_digits=15, decimal_places=3, verbose_name='Требуемое количество')
    unit = models.CharField(max_length=20, choices=UnitChoices.choices, default=UnitChoices.SHT, verbose_name='Единица измерения')

    class Meta:
        """
        Метаданные модели RecipeItem.

        Атрибуты:
            verbose_name: человекочитаемое имя модели
            verbose_name_plural: множественное число
        """
        verbose_name = 'Компонент рецепта'
        verbose_name_plural = 'Компоненты рецепта'

    def __str__(self):
        return f"{self.quantity_required} {self.get_unit_display()} of {self.material.name}"
