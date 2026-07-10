"""
Finance models - управление финансами.

Этот модуль содержит модели для управления расходами,
оплатой работников и финансовой аналитикой.

ВАЖНО: Все финансовые данные доступны только владельцу (owner).
"""
from django.db import models
from apps.core.models import TimestampedModel


class ExpenseCategory(models.TextChoices):
    """
    Категории расходов.

    RENT: аренда
    ELECTRICITY: электричество
    WATER: вода
    TRANSPORT: транспорт
    DELIVERY: доставка
    TAXES: налоги
    SALARY: зарплата работников
    ADVANCE: аванс работникам
    EQUIPMENT_REPAIR: ремонт оборудования
    TOOLS: покупка инструментов
    CONSUMABLES: расходные материалы
    MATERIAL_LOSS: потеря материала
    DEFECT: брак
    UNFORESEEN: непредвиденные расходы
    OWNER_WITHDRAWAL: личный вывод средств владельцем
    WORKER_DEBT: долги работников
    CLIENT_REFUND: возвраты клиентам
    OTHER: другое
    """
    RENT = 'rent', 'Ижара'
    ELECTRICITY = 'electricity', 'Электр энергия'
    WATER = 'water', 'Сув'
    TRANSPORT = 'transport', 'Транспорт'
    DELIVERY = 'delivery', 'Етказиб бериш'
    TAXES = 'taxes', 'Солиқлар'
    SALARY = 'salary', 'Ишчилар иш ҳақи'
    ADVANCE = 'advance', 'Ишчиларга аванс'
    EQUIPMENT_REPAIR = 'equipment_repair', 'Ускуна таъмири'
    TOOLS = 'tools', 'Асбоб сотиб олиш'
    CONSUMABLES = 'consumables', 'Сарфлаш материаллари'
    MATERIAL_LOSS = 'material_loss', 'Материал йўқотиш'
    DEFECT = 'defect', 'Брак'
    UNFORESEEN = 'unforeseen', 'Кутилмаган харажатлар'
    OWNER_WITHDRAWAL = 'owner_withdrawal', 'Эгасининг шахсий чиқими'
    WORKER_DEBT = 'worker_debt', 'Ишчилар қарзлари'
    CLIENT_REFUND = 'client_refund', 'Мижозларга қайтариш'
    OTHER = 'other', 'Бошқа'


class PaymentMethod(models.TextChoices):
    """
    Способы оплаты.

    CASH: наличные
    CARD: карта
    TRANSFER: перевод
    OTHER: другое
    """
    CASH = 'cash', 'Нақд'
    CARD = 'card', 'Карта'
    TRANSFER = 'transfer', 'Ўтказма'
    OTHER = 'other', 'Бошқа'


class Expense(TimestampedModel):
    """
    Модель расхода.

    Хранит информацию о всех расходах компании.
    Доступна только владельцу.

    Поля:
        category: CharField - категория расхода
        amount: DecimalField - сумма расхода
        date: DateField - дата расхода
        comment: TextField - комментарий
        receipt_photo: ImageField - фото чека
        created_by: ForeignKey - кто добавил расход
        payment_method: CharField - способ оплаты

    Особенности:
        - Автоматические временные метки (TimestampedModel)
        - Фото чека для подтверждения
        - Категоризация расходов
    """
    category = models.CharField(max_length=30, choices=ExpenseCategory.choices, db_index=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    date = models.DateField(db_index=True)
    comment = models.TextField(blank=True, default='')
    receipt_photo = models.ImageField(upload_to='finance/receipts/', blank=True, null=True)
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='expenses')
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH)

    class Meta:
        verbose_name = 'Expense'
        verbose_name_plural = 'Expenses'
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['category', 'date']),
            models.Index(fields=['date']),
        ]

    def __str__(self):
        """
        Строковое представление расхода.

        Возвращает категорию и сумму.
        """
        return f"{self.get_category_display()} - {self.amount}"


class LaborRate(TimestampedModel):
    """
    Модель ставки оплаты труда.

    Хранит ставки оплаты за единицу работы для разных типов продукции.
    Доступна только владельцу.

    Поля:
        product: ForeignKey - готовая продукция
        operation: CharField - тип операции (резка, полировка и т.д.)
        rate_per_unit: DecimalField - ставка за единицу
        unit: CharField - единица измерения

    Особенности:
        - Автоматические временные метки (TimestampedModel)
        - Разные ставки для разных операций
    """
    class OperationType(models.TextChoices):
        """
        Типы операций.

        CUTTING: резка
        POLISHING: полировка
        MOUNTING: монтаж
        PACKING: упаковка
        OTHER: другое
        """
        CUTTING = 'cutting', 'Кесиш'
        POLISHING = 'polishing', 'Сийлаш'
        MOUNTING = 'mounting', 'Монтаж'
        PACKING = 'packing', 'Қутлаш'
        OTHER = 'other', 'Бошқа'

    product = models.ForeignKey('warehouse.FinishedProduct', on_delete=models.CASCADE, related_name='labor_rates')
    operation = models.CharField(max_length=20, choices=OperationType.choices)
    rate_per_unit = models.DecimalField(max_digits=15, decimal_places=2)
    unit = models.CharField(max_length=20, choices='warehouse.models.UnitChoices.choices')

    class Meta:
        verbose_name = 'Labor Rate'
        verbose_name_plural = 'Labor Rates'
        ordering = ['product', 'operation']
        unique_together = ['product', 'operation']

    def __str__(self):
        """
        Строковое представление ставки.

        Возвращает продукт, операцию и ставку.
        """
        return f"{self.product.name} - {self.get_operation_display()}: {self.rate_per_unit} / {self.unit}"


class WorkerPayment(TimestampedModel):
    """
    Модель оплаты работника.

    Хранит информацию о выплатах работникам.
    Доступна только владельцу.

    Поля:
        worker: ForeignKey - работник
        amount: DecimalField - сумма выплаты
        payment_date: DateField - дата выплаты
        payment_type: CharField - тип выплаты (зарплата, аванс, премия)
        comment: TextField - комментарий
        created_by: ForeignKey - кто создал запись

    Особенности:
        - Автоматические временные метки (TimestampedModel)
        - Разные типы выплат
    """
    class PaymentType(models.TextChoices):
        """
        Типы выплат.

        SALARY: зарплата
        ADVANCE: аванс
        BONUS: премия
        OTHER: другое
        """
        SALARY = 'salary', 'Иш ҳақи'
        ADVANCE = 'advance', 'Аванс'
        BONUS = 'bonus', 'Мукофот'
        OTHER = 'other', 'Бошқа'

    worker = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_date = models.DateField(db_index=True)
    payment_type = models.CharField(max_length=20, choices=PaymentType.choices, default=PaymentType.SALARY)
    comment = models.TextField(blank=True, default='')
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='created_payments')

    class Meta:
        verbose_name = 'Worker Payment'
        verbose_name_plural = 'Worker Payments'
        ordering = ['-payment_date', '-created_at']
        indexes = [
            models.Index(fields=['worker', 'payment_date']),
            models.Index(fields=['payment_date']),
        ]

    def __str__(self):
        """
        Строковое представление выплаты.

        Возвращает работника, сумму и тип выплаты.
        """
        return f"{self.worker.username} - {self.amount} ({self.get_payment_type_display()})"
