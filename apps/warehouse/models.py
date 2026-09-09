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


class StorageZoneChoices(models.TextChoices):
    """
    Зоны хранения на складе сырья (макет «Хомашё омбори»).

    Вместо свободного текста storage_location макет показывает выбор зоны
    (А/Б/В) — по ней можно фильтровать и видеть занятость склада.
    """
    A = 'a', 'А зона'
    B = 'b', 'Б зона'
    C = 'c', 'В зона'
    OTHER = 'other', 'Бошқа'


class Warehouse(TimestampedModel, SoftDeleteModel):
    """
    Физический склад компании (макет «Асосий омбор» с переключателем складов).

    До этого склад был один и подразумевался неявно: у материала было только
    текстовое «место хранения». Компания с двумя площадками не могла ни
    отфильтровать остатки по складу, ни увидеть загруженность каждого.

    Поля:
        name: название («Асосий омбор»)
        code: короткий код для ярлыков и отчётов
        address: адрес площадки
        total_area: общая площадь, м² (макет: «Жами майдон 420 м²»)
        is_default: склад по умолчанию — туда попадают материалы без явного
            указания склада; ровно один на компанию
    """
    company = models.ForeignKey(
        'companies.Company', on_delete=models.CASCADE, related_name='warehouses',
        null=True, verbose_name='Компания',
    )
    name = models.CharField(max_length=150, verbose_name='Название')
    code = models.CharField(max_length=30, blank=True, default='', verbose_name='Код')
    address = models.CharField(max_length=255, blank=True, default='', verbose_name='Адрес')
    total_area = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        validators=[MinValueValidator(Decimal('0'))], verbose_name='Общая площадь, м²',
    )
    is_default = models.BooleanField(default=False, verbose_name='Склад по умолчанию')
    comment = models.TextField(blank=True, default='', verbose_name='Комментарий')

    class Meta:
        verbose_name = 'Склад'
        verbose_name_plural = 'Склады'
        ordering = ['-is_default', 'name']
        constraints = [
            # Название склада уникально внутри компании: два «Асосий омбор»
            # в одном списке невозможно различить.
            models.UniqueConstraint(
                fields=['company', 'name'], name='warehouse_unique_name_per_company',
            ),
            # Склад по умолчанию ровно один — иначе непонятно, куда класть
            # материал, у которого склад не указан.
            models.UniqueConstraint(
                fields=['company'], condition=models.Q(is_default=True),
                name='warehouse_single_default_per_company',
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def occupied_area(self):
        """Занятая площадь: сумма занятости ячеек этого склада."""
        return sum((cell.occupied_area for cell in self.cells.all()), Decimal('0'))

    @property
    def occupancy_percent(self):
        """
        Процент занятости склада (макет: «банд 86.1 %, бўш 13.9 %»).

        Считаем от общей площади склада, если она задана; иначе — от суммы
        вместимостей ячеек, чтобы показатель не был нулевым у складов, где
        площадь площадки не заполняли.
        """
        base = self.total_area or sum(
            (cell.capacity_area for cell in self.cells.all()), Decimal('0')
        )
        if not base:
            return Decimal('0')
        return (self.occupied_area / base * 100).quantize(Decimal('0.1'))


class WarehouseCell(TimestampedModel, SoftDeleteModel):
    """
    Ячейка хранения А-01…А-08 (макет «Омбордаги жойлашув»).

    Занятость ячейки не вводится руками, а считается по размещённым в ней
    материалам: руками введённая занятость мгновенно расходится с реальными
    приходами и расходами.
    """
    company = models.ForeignKey(
        'companies.Company', on_delete=models.CASCADE, related_name='warehouse_cells',
        null=True, verbose_name='Компания',
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, related_name='cells', verbose_name='Склад',
    )
    code = models.CharField(max_length=20, verbose_name='Код ячейки')
    zone = models.CharField(
        max_length=10, choices=StorageZoneChoices.choices, blank=True, default='',
        verbose_name='Зона',
    )
    capacity_area = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        validators=[MinValueValidator(Decimal('0'))], verbose_name='Вместимость, м²',
    )

    class Meta:
        verbose_name = 'Ячейка хранения'
        verbose_name_plural = 'Ячейки хранения'
        ordering = ['warehouse', 'code']
        constraints = [
            models.UniqueConstraint(
                fields=['warehouse', 'code'], name='cell_unique_code_per_warehouse',
            ),
        ]

    def __str__(self):
        return f'{self.warehouse_id}:{self.code}'

    @property
    def occupied_area(self):
        """
        Занятая площадь ячейки.

        Берём площадь, указанную при размещении партии (occupied_area), а если
        она не указана — количество материала, измеряемого в м²/м³: для таких
        материалов количество и есть занимаемая площадь.
        """
        total = Decimal('0')
        for material in self.materials.all():
            total += material.effective_occupied_area
        return total

    @property
    def occupancy_percent(self):
        if not self.capacity_area:
            return Decimal('0')
        return (self.occupied_area / self.capacity_area * 100).quantize(Decimal('0.1'))


class MaterialConditionChoices(models.TextChoices):
    """
    Состояние (качество) партии материала — макет «Хом ашё омбори».

    Плита с трещиной физически на складе есть, но в дело не годится. Без
    этого поля склад показывал её как обычный остаток, и нехватку под заказ
    обнаруживали только в цеху.
    """
    EXCELLENT = 'excellent', 'Отличное'
    GOOD = 'good', 'Хорошее'
    POOR = 'poor', 'Ниже среднего'
    CRITICAL = 'critical', 'Критическое'


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
    KG = 'kg', 'Килограмм'
    M3 = 'm3', 'Кубический метр'

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
    # Штрихкод материала (макет: «Баркод», сканер по нему ищет на складе).
    barcode = models.CharField(max_length=128, blank=True, default='',
                               db_index=True, verbose_name='Штрихкод')
    # Зона хранения (А/Б/В) — макет «Хомашё омбори».
    storage_zone = models.CharField(max_length=10, choices=StorageZoneChoices.choices,
                                    blank=True, default='', verbose_name='Зона хранения')
    storage_location = models.CharField(max_length=255, blank=True, verbose_name='Место хранения')
    # ── Размещение на складе (макеты «Асосий омбор» и «Омбордаги жойлашув») ──
    # Раньше место хранения было только текстом: по нему нельзя ни отфильтровать
    # остатки по складу, ни посчитать занятость ячейки.
    warehouse = models.ForeignKey(
        'warehouse.Warehouse', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='materials', verbose_name='Склад',
    )
    cell = models.ForeignKey(
        'warehouse.WarehouseCell', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='materials', verbose_name='Ячейка хранения',
    )
    # Состояние партии (макет «Аъло / Яхши / Қуйида / Критик»).
    condition = models.CharField(
        max_length=20, choices=MaterialConditionChoices.choices,
        blank=True, default='', verbose_name='Состояние материала',
    )
    # Сколько площади занимает партия. Для материалов в м²/м³ можно не
    # заполнять — тогда занятостью считается само количество.
    occupied_area = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))], verbose_name='Занимает площади, м²',
    )
    # ПОТРЕБНОСТЬ заказов (demand), а не физический резерв: сколько сырья
    # требуется активным заказам по рецептам. Может превышать quantity
    # (overbooking) — тогда shortage_quantity > 0, а доступность проверяется
    # по физическому остатку в момент выдачи/подтверждения. Заполняется при
    # создании заказа (Order.apply_raw_material_requirements), снимается при
    # отмене/выдаче и при подтверждении работы (сырьё физически израсходовано).
    required_for_orders = models.DecimalField(
        max_digits=15, decimal_places=3, default=0,
        validators=[MinValueValidator(Decimal('0'))], verbose_name='Требуется под заказы',
    )
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
        constraints = [
            models.CheckConstraint(
                check=models.Q(quantity__gte=0),
                name='rawmaterial_quantity_nonnegative',
            ),
            models.CheckConstraint(
                check=models.Q(required_for_orders__gte=0),
                name='rawmaterial_required_nonnegative',
            ),
            # НАМЕРЕННО нет ограничения required_for_orders <= quantity:
            # потребность заказов может превышать физический остаток (overbooking).
            # Заказ на большее количество, чем есть на складе, создаётся и
            # помечается has_material_shortage, а нехватка проверяется по
            # физическому остатку при выдаче/подтверждении (record_outgoing/
            # confirm_work). Ограничение «required <= quantity» ломало бы это
            # (IntegrityError вместо понятного отказа) и несовместимо с
            # record_outgoing(ignore_required=True).
        ]

    def __str__(self):
        """
        Строковое представление материала.

        Возвращает название с количеством и единицей измерения.
        """
        return f"{self.name} ({self.quantity} {self.get_unit_display()})"

    @property
    def available_quantity(self):
        """
        Доступное количество с учётом потребности заказов.

        quantity - required_for_orders. Может быть ОТРИЦАТЕЛЬНЫМ: это
        означает нехватку (потребность заказов превышает физический остаток),
        а не ошибку — величина нехватки видна в shortage_quantity.

        Возвращает:
            Decimal - quantity - required_for_orders
        """
        return self.quantity - self.required_for_orders

    @property
    def shortage_quantity(self):
        """
        Нехватка для покрытия потребности заказов (>= 0).

        max(required_for_orders - quantity, 0). Ноль — остатка хватает.
        """
        return max(self.required_for_orders - self.quantity, Decimal('0'))

    @property
    def is_low_stock(self):
        """
        Проверяет, находится ли материал на низком остатке.

        Учитывает потребность заказов: доступно для новых заказов лишь
        available_quantity. При нехватке (available < 0) — безусловно низкий.

        Возвращает:
            bool - True если available_quantity <= min_stock
        """
        return self.available_quantity <= self.min_stock

    @property
    def effective_occupied_area(self):
        """
        Сколько площади реально занимает партия (для занятости ячейки).

        Если площадь указана явно — берём её. Если нет, но материал меряется
        в м²/м³, площадь и есть количество. Штучный материал без явной
        площади ячейку «не занимает»: придумывать за пользователя габариты
        плиты нельзя.
        """
        if self.occupied_area is not None:
            return self.occupied_area
        if self.unit in (UnitChoices.M2, UnitChoices.M3):
            return self.quantity
        return Decimal('0')

    @property
    def stock_severity(self):
        """
        Градация остатка для карточки склада (макет «Минимум қолдиқлар»).

        Раньше был только булев is_low_stock, и «почти закончилось» выглядело
        так же, как «уже не хватает под заказы»:
            critical — доступного меньше половины минимума или уже нехватка;
            low      — доступное не выше минимума;
            ok       — запас в норме.
        """
        available = self.available_quantity
        if available <= 0 or (self.min_stock and available < self.min_stock / 2):
            return 'critical'
        if available <= self.min_stock:
            return 'low'
        return 'ok'


class FinishedProduct(TimestampedModel, SoftDeleteModel):
    """
    Модель готовой продукции на складе.

    Хранит информацию о готовых изделиях, доступных для продажи.

    Поля:
        name: CharField - название продукции
        category: CharField - категория продукции
        unit: CharField - единица измерения
        quantity: DecimalField - общее количество на складе
        photo: ImageField - фото продукции
        description: TextField - описание
        min_stock: DecimalField - минимальный остаток для предупреждений
        required_for_orders: DecimalField - потребность заказов (demand)
        cost_price: DecimalField - себестоимость (ФИНАНСОВОЕ ПОЛЕ - только owner)
        sale_price: DecimalField - цена продажи (ФИНАНСОВОЕ ПОЛЕ - только owner)

    Свойства:
        available_quantity: DecimalField - доступное количество (quantity - required)
        shortage_quantity: DecimalField - нехватка (required - quantity, >= 0)
        is_low_stock: bool - True если available_quantity <= min_stock

    Потребность заказов: поле заполняется при создании заказа на товар
    (apps/orders — Order.apply_product_requirement), снимается при отмене,
    удалении и выдаче заказа (Order.release_product_requirement). Это НЕ
    физический резерв: потребность может превышать остаток (overbooking),
    нехватка помечается has_product_shortage и проверяется по физическому
    остатку в момент выдачи.
    """
    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='finished_products', null=True, verbose_name='Компания')
    name = models.CharField(max_length=255, verbose_name='Название')
    category = models.CharField(max_length=100, blank=True, verbose_name='Категория')
    unit = models.CharField(max_length=20, choices=UnitChoices.choices, default=UnitChoices.IZDELIE, verbose_name='Единица измерения')
    quantity = models.DecimalField(max_digits=15, decimal_places=3, default=0,
                                   validators=[MinValueValidator(Decimal('0'))], verbose_name='Количество')
    photo = models.ImageField(upload_to='products/', blank=True, null=True, validators=[validate_file_size], verbose_name='Фото')
    description = models.TextField(blank=True, verbose_name='Описание')
    min_stock = models.DecimalField(max_digits=15, decimal_places=3, default=0,
                                    validators=[MinValueValidator(Decimal('0'))], verbose_name='Минимальный остаток')
    required_for_orders = models.DecimalField(max_digits=15, decimal_places=3, default=0,
                                        validators=[MinValueValidator(Decimal('0'))], verbose_name='Требуется под заказы')
    arrival_date = models.DateField(null=True, blank=True, verbose_name='Дата поступления')
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
        constraints = [
            models.CheckConstraint(
                check=models.Q(quantity__gte=0),
                name='finishedproduct_quantity_nonnegative',
            ),
            models.CheckConstraint(
                check=models.Q(required_for_orders__gte=0),
                name='finishedproduct_required_nonnegative',
            ),
            # НАМЕРЕННО нет ограничения required_for_orders <= quantity: см.
            # RawMaterial — резерв может превышать физический остаток
            # (overbooking), нехватка проверяется при выдаче/подтверждении.
        ]

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

        Учитывает потребность заказов (может быть отрицательным — нехватка).

        Возвращает:
            DecimalField - quantity - required_for_orders
        """
        return self.quantity - self.required_for_orders

    @property
    def shortage_quantity(self):
        """
        Нехватка для покрытия потребности заказов (>= 0).
        """
        return max(self.required_for_orders - self.quantity, Decimal('0'))

    @property
    def is_low_stock(self):
        """
        Проверяет, находится ли продукция на низком остатке.

        Учитывает потребность заказов: при нехватке (available < 0) — низкий.

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
        related_order: ForeignKey - связанный заказ (опционально, SET_NULL:
            история движений переживает удаление заказа)

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
        RETURN: возврат материала на склад (вкладка «Қайтарилган» в макете
            «Материал ҳаракатлари»): цех вернул неиспользованный остаток или
            материал вернули поставщику. Раньше такой возврат приходилось
            проводить обычным приходом, и в истории он был неотличим от
            новой поставки.
        """
        INCOMING = 'incoming', 'Приход'
        OUTGOING = 'outgoing', 'Расход'
        PRODUCTION_IN = 'production_in', 'Приход с производства'
        PRODUCTION_OUT = 'production_out', 'Расход на производство'
        ADJUSTMENT = 'adjustment', 'Корректировка'
        LOSS = 'loss', 'Потеря/Брак'
        RETURN = 'return', 'Возврат'

    class OutgoingPurpose(models.TextChoices):
        """
        Назначение ручного расхода (макет «Материални ишлатиш» → «Қайси мақсадда»).

        Тип движения отвечает на вопрос «что произошло» (расход, потеря,
        корректировка), а назначение — «зачем»: в производство по заказу, на
        образец, на внутренние нужды. Раньше это писали свободным текстом в
        причину, и сгруппировать расход по назначению было невозможно.
        """
        PRODUCTION = 'production', 'Производство'
        SAMPLE = 'sample', 'Образец'
        INTERNAL = 'internal', 'Внутренние нужды'
        WRITE_OFF = 'write_off', 'Списание'
        OTHER = 'other', 'Другое'

    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='stock_movements', null=True, verbose_name='Компания')
    movement_type = models.CharField(max_length=20, choices=MovementType.choices, db_index=True, verbose_name='Тип движения')
    purpose = models.CharField(
        max_length=20, choices=OutgoingPurpose.choices, blank=True, default='',
        verbose_name='Назначение расхода',
    )
    material = models.ForeignKey(RawMaterial, on_delete=models.CASCADE, null=True, blank=True, related_name='movements', verbose_name='Материал')
    product = models.ForeignKey(FinishedProduct, on_delete=models.CASCADE, null=True, blank=True, related_name='movements', verbose_name='Товар')
    quantity = models.DecimalField(max_digits=15, decimal_places=3, verbose_name='Количество')
    price_per_unit = models.DecimalField(max_digits=15, decimal_places=2, default=0, verbose_name='Цена за единицу')
    reason = models.CharField(max_length=255, blank=True, verbose_name='Причина')
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='stock_movements', verbose_name='Кем создано')
    # Номер документа прихода/расхода (макет: «Хужжат раками» №К-1258).
    document_number = models.CharField(max_length=100, blank=True, default='',
                                       verbose_name='Номер документа')
    # Документ прихода, породивший движение (макет «Материални қабул қилиш»:
    # один документ — несколько позиций). Раньше связь была только через
    # текстовый номер документа: собрать движения одной операции было нечем.
    receipt = models.ForeignKey(
        'warehouse.GoodsReceipt', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movements', verbose_name='Документ прихода',
    )
    related_order = models.ForeignKey(
        'orders.Order', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_movements', verbose_name='Связанный заказ',
    )

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

class GoodsReceipt(TimestampedModel):
    """
    Документ прихода: одна поставка — несколько материалов.

    Макет «Материални қабул қилиш» задаёт поставщика, номер документа и дату
    ОДИН раз, а ниже перечисляет позиции («Яна материал қўшиш»). Раньше приход
    оформлялся по одному материалу за операцию, а общие реквизиты дублировались
    строкой в каждом движении: нельзя было ни открыть поставку целиком, ни
    понять, какие позиции пришли вместе.

    Проведение документа атомарно: либо приходуются все позиции, либо ни одна
    (см. services.create_goods_receipt).
    """
    company = models.ForeignKey(
        'companies.Company', on_delete=models.CASCADE, related_name='goods_receipts',
        null=True, verbose_name='Компания',
    )
    supplier = models.CharField(max_length=255, blank=True, default='', verbose_name='Поставщик')
    document_number = models.CharField(max_length=100, blank=True, default='', verbose_name='Номер документа')
    receipt_date = models.DateField(
        null=True, blank=True, validators=[validate_not_future], verbose_name='Дата прихода',
    )
    comment = models.TextField(blank=True, default='', verbose_name='Комментарий')
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True,
        related_name='goods_receipts', verbose_name='Кем создан',
    )

    class Meta:
        verbose_name = 'Документ прихода'
        verbose_name_plural = 'Документы прихода'
        ordering = ['-created_at']
        constraints = [
            # Идемпотентность: повторная отправка той же формы (двойной клик,
            # ретрай мобильной сети) не создаст вторую поставку с тем же
            # номером у того же поставщика. Пустой номер не ограничивается —
            # такие документы бывают у поставок без бумаг.
            models.UniqueConstraint(
                fields=['company', 'supplier', 'document_number'],
                condition=~models.Q(document_number=''),
                name='goods_receipt_unique_document',
            ),
        ]

    def __str__(self):
        return f'{self.document_number or "—"} ({self.supplier or "—"})'

    @property
    def total_quantity(self):
        return sum((line.quantity for line in self.lines.all()), Decimal('0'))

    @property
    def total_amount(self):
        """Сумма документа — ФИНАНСОВОЕ значение, отдаётся только владельцу."""
        return sum(
            (line.quantity * (line.price_per_unit or Decimal('0')) for line in self.lines.all()),
            Decimal('0'),
        )


class GoodsReceiptLine(models.Model):
    """
    Позиция документа прихода: материал, количество и цена.

    Цена — финансовое поле: её задаёт и видит только владелец (как в операции
    прихода одного материала).
    """
    receipt = models.ForeignKey(
        GoodsReceipt, on_delete=models.CASCADE, related_name='lines', verbose_name='Документ',
    )
    material = models.ForeignKey(
        RawMaterial, on_delete=models.RESTRICT, related_name='receipt_lines',
        verbose_name='Материал',
    )
    quantity = models.DecimalField(
        max_digits=15, decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))], verbose_name='Количество',
    )
    price_per_unit = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        validators=[MinValueValidator(Decimal('0'))], verbose_name='Цена за единицу',
    )

    class Meta:
        verbose_name = 'Позиция прихода'
        verbose_name_plural = 'Позиции прихода'
        ordering = ['id']

    def __str__(self):
        return f'{self.material_id}: {self.quantity}'


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
    # Артикул рецепта из макета («RCP-001»): по нему рецепт называют в цеху и
    # в задании, названия товара для этого мало — у одного товара бывает
    # несколько рецептов под разные габариты.
    code = models.CharField(max_length=30, blank=True, default='', verbose_name='Код рецепта')
    # Габариты изделия, на которое рассчитана норма (макет: «Ўлчам 2000 × 600
    # мм», «Қалинлик 20 мм»). Раньше норма висела в воздухе: 2.2 м² мрамора —
    # на какое изделие, из карточки было не понять.
    size = models.CharField(max_length=100, blank=True, default='', verbose_name='Размер изделия')
    thickness = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.01'))], verbose_name='Толщина, мм',
    )
    # Сколько готовых изделий даёт ОДНА закладка по этому рецепту
    # (макет: «Ҳосил бўладиган маҳсулот 1 дона»). До этого выход всегда
    # подразумевался равным единице: норма умножалась на количество изделий
    # напрямую. Рецепт «из одной плиты выходит 4 подоконника» описать было
    # нечем — приходилось делить норму вручную и ошибаться.
    output_quantity = models.DecimalField(
        max_digits=15, decimal_places=3, default=Decimal('1'),
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name='Выход готовой продукции',
    )
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
    # Минимум строго больше нуля: отрицательная норма превращала требования по
    # рецепту в отрицательные, confirm_work «дорисовывал» материал из воздуха.
    quantity_required = models.DecimalField(
        max_digits=15, decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        verbose_name='Требуемое количество',
    )
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
